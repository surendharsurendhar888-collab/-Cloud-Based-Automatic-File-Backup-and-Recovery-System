"""
Cloud Based Automatic File Backup and Recovery System
======================================================
Flask backend with SQLite (metadata) + Supabase Storage (files)
Author: CloudBackup System
"""

import os
import sqlite3
import hashlib
import uuid
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file
)
from werkzeug.utils import secure_filename
import tempfile
import mimetypes
from dotenv import dotenv_values
from groq import Groq
from authlib.integrations.flask_client import OAuth
import string
import random

# ─── Environment Setup ────────────────────────────────────────────────────────
BASE_DIR_ENV = os.path.dirname(os.path.abspath(__file__))
env_config = dotenv_values(os.path.join(BASE_DIR_ENV, ".env"))
GROQ_API_KEY = env_config.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")

# Initialise Groq client (will be None-safe inside ask_ai)
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ─── Supabase client ────────────────────────────────────────────────────────
from supabase import create_client, Client

SUPABASE_URL = env_config.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_KEY = env_config.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
BUCKET_NAME  = "files"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[WARNING] Supabase credentials missing. Ensure SUPABASE_URL and SUPABASE_KEY are in your .env file.")

# Create Supabase client (supabase-py 2.x accepts the publishable key directly)
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[ERROR] Failed to initialize Supabase client: {e}")
        supabase = None
else:
    supabase = None

# ─── Flask app setup ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "cloudbackup_super_secret_key_2024"  # session encryption key

# Folders
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR  = os.path.join(BASE_DIR, "uploads")
DB_PATH     = os.path.join(BASE_DIR, "database.db")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── OAuth Setup ──────────────────────────────────────────────────────────────
oauth = OAuth(app)
GOOGLE_CLIENT_ID = env_config.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env_config.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET")

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

# ─── Database helpers ─────────────────────────────────────────────────────────

def get_db():
    """Open a SQLite connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables on first run."""
    conn = get_db()
    cur  = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL
        )
    """)

    # Folders table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            parent_id   INTEGER,
            user_id     INTEGER NOT NULL,
            created_at  TEXT    NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES folders(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Files/versions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT    NOT NULL,
            supabase_path TEXT    NOT NULL,
            version       INTEGER NOT NULL DEFAULT 1,
            timestamp     TEXT    NOT NULL,
            user_id       INTEGER NOT NULL,
            file_hash     TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Migration for adding file_hash to existing tables
    try:
        cur.execute("ALTER TABLE files ADD COLUMN file_hash TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists

    # Migration for adding folder_id to existing files table
    try:
        cur.execute("ALTER TABLE files ADD COLUMN folder_id INTEGER REFERENCES folders(id)")
    except sqlite3.OperationalError:
        pass

    # Migration for adding file_size to existing tables
    try:
        cur.execute("ALTER TABLE files ADD COLUMN file_size INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Column already exists

    # Migration for adding role to existing tables
    try:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    # Migration for adding google_id and email to existing tables
    try:
        cur.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration for adding is_deleted, deleted_at, is_starred to files table
    try:
        cur.execute("ALTER TABLE files ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE files ADD COLUMN deleted_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE files ADD COLUMN is_starred INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Consolidated Activity Log table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            action      TEXT    NOT NULL, -- upload, preview, download, restore, login
            file_name   TEXT,
            version     INTEGER,
            folder_id   INTEGER,
            timestamp   TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Recent Activity table for dashboard
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recent_activity (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            file_id     INTEGER,
            action      TEXT,
            timestamp   TEXT    NOT NULL
        )
    """)

    # Migration for merging activity_logs data if it exists
    try:
        cur.execute("INSERT INTO activity_log (user_id, action, file_name, version, timestamp) SELECT user_id, action_type, file_name, version, timestamp FROM activity_logs")
        cur.execute("DROP TABLE activity_logs")
    except sqlite3.OperationalError:
        pass

    # --- Admin user creation logic added here ---
    admin_user = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not admin_user:
        cur.execute(
            "INSERT INTO users (username, password, role, created_at) VALUES (?, ?, ?, ?)",
            ("admin", hash_password("admin123"), "admin", timestamp)
        )
        print("Admin user created")
    else:
        # Ensure existing admin has the admin role
        cur.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
    # --------------------------------------------

    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    """SHA-256 hash a password."""
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(user_id, action, file_name=None, version=None, folder_id=None):
    """Log a user action to the activity_log table."""
    conn = get_db()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO activity_log (user_id, action, file_name, version, folder_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, file_name, version, folder_id, timestamp)
    )
    conn.commit()
    conn.close()

def log_recent_activity(user_id, file_id, action):
    """Update or insert into recent_activity table."""
    conn = get_db()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # We want to keep unique recent interactions per file/action combo or just latest?
    # Usually recent means "when was the last time I touched this".
    # Let's check if there's already an entry for this file and action.
    existing = conn.execute(
        "SELECT id FROM recent_activity WHERE user_id = ? AND file_id = ? AND action = ?",
        (user_id, file_id, action)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE recent_activity SET timestamp = ? WHERE id = ?",
            (timestamp, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO recent_activity (user_id, file_id, action, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, file_id, action, timestamp)
        )
    conn.commit()
    conn.close()


def ask_ai(message, context_stats):
    """Query Groq API (llama-3.1-8b-instant) with context about the user's storage and recent activity."""
    if not groq_client:
        return "Error: GROQ_API_KEY is not configured in the backend."

    recent_activity_str = ""
    if context_stats.get('recent_activity'):
        recent_activity_str = "Recent User Activity:\n"
        for act in context_stats['recent_activity']:
            recent_activity_str += f"- {act['action'].capitalize()} '{act['file_name']}' (v{act['version'] or 1}) on {act['timestamp']}\n"

    system_prompt = (
        "You are CloudShield AI, a smart contextual Cloud Backup AI Assistant. "
        "Keep all replies accurate, contextual, and short — under 3 sentences when possible. "
        f"User storage stats: {context_stats['total_files']} file(s), "
        f"{context_stats['total_versions']} version(s), "
        f"{context_stats['total_folders']} folder(s), "
        f"{context_stats['total_storage']} used.\n"
        f"{recent_activity_str}\n"
        "Use this real database data to answer questions about recent uploads, deletes, downloads, or restores. "
        "If asked about recent activity, list the specific filenames and actions. "
        "Be helpful, factual, and professional."
    )

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": message}
            ],
            temperature=0.2,
            max_tokens=150
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Sorry, I encountered an error communicating with my AI brain: {str(e)}"

# ─── Auth helpers ─────────────────────────────────────────────────────────────

def login_required(f):
    """Decorator: redirect to /login if not authenticated."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ─── Folder Helpers ──────────────────────────────────────────────────────────

def get_folder_path_list(folder_id, conn):
    """Returns a list of dicts [{'id': 1, 'name': 'Folder1'}, ...] for breadcrumbs."""
    path = []
    current_id = folder_id
    while current_id:
        row = conn.execute("SELECT id, name, parent_id FROM folders WHERE id = ?", (current_id,)).fetchone()
        if not row:
            break
        path.insert(0, {"id": row["id"], "name": row["name"]})
        current_id = row["parent_id"]
    return path

def get_supabase_folder_path(folder_id, conn):
    """Returns a string path like 'Folder1/Folder2' or empty string."""
    if not folder_id:
        return ""
    path_list = get_folder_path_list(folder_id, conn)
    return "/".join([secure_filename(f["name"]) for f in path_list])

# Initialize database tables
init_db()

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Render the landing page for unauthenticated users, otherwise dashboard."""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


# ── Login ─────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if user and user["password"] == hash_password(password):
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            
            # Use dictionary-like access cautiously in case column missing due to migration timing
            try:
                session["role"] = user["role"]
                session["avatar"] = user["avatar"]
            except (IndexError, KeyError):
                session["role"] = "user"
                session["avatar"] = None

            flash(f"Welcome back, {username}!", "success")
            log_activity(user["id"], "login")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html")


# ── Google OAuth ──────────────────────────────────────────────────────────────
@app.route("/login/google")
def login_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash("Google Sign-In is not configured by the administrator.", "danger")
        return redirect(url_for("login"))
    # Use dynamic redirect URI for production compatibility
    redirect_uri = url_for('auth_google', _external=True)
    
    # Render and other proxies might use http internally; force https for production OAuth
    if 'localhost' not in redirect_uri and redirect_uri.startswith('http://'):
        redirect_uri = redirect_uri.replace('http://', 'https://')
        
    return oauth.google.authorize_redirect(
        redirect_uri,
        prompt="select_account consent"
    )

@app.route("/auth/google")
def auth_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash("Google Sign-In is not configured.", "danger")
        return redirect(url_for("login"))
    try:
        # Use the same hardcoded redirect_uri for the token exchange
        token = oauth.google.authorize_access_token()
        user_info = token.get("userinfo")
    except Exception as e:
        print(f"Google OAuth Error: {e}")
        flash("Google login failed.", "danger")
        return redirect(url_for("login"))

    if not user_info:
        flash("Could not fetch user info from Google.", "danger")
        return redirect(url_for("login"))

    google_id = user_info.get("sub")
    email = user_info.get("email")
    username = user_info.get("name") or email.split("@")[0]

    conn = get_db()
    # Check if user exists by google_id
    user = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    
    if not user:
        # Check if user exists by email or username
        user = conn.execute("SELECT * FROM users WHERE email = ? OR username = ?", (email, username)).fetchone()
        if user:
            # Update existing user with google_id
            conn.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, user["id"]))
            conn.commit()
        else:
            # Create new user
            random_pwd = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            hashed_pwd = hash_password(random_pwd)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, password, role, google_id, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (username, hashed_pwd, "user", google_id, email, timestamp)
                )
                conn.commit()
                user_id = cur.lastrowid
                user = {"id": user_id, "username": username, "role": "user"}
            except sqlite3.IntegrityError:
                # Fallback if username exists
                username = f"{username}_{str(uuid.uuid4())[:4]}"
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, password, role, google_id, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (username, hashed_pwd, "user", google_id, email, timestamp)
                )
                conn.commit()
                user_id = cur.lastrowid
                user = {"id": user_id, "username": username, "role": "user"}

    conn.close()

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    
    try:
        session["role"] = user["role"]
        session["avatar"] = user.get("avatar")
    except Exception:
        session["role"] = "user"
        session["avatar"] = None

    flash(f"Welcome, {session['username']}!", "success")
    return redirect(url_for("dashboard"))


# ── Register ──────────────────────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not username or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        conn = get_db()
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                (username, hash_password(password), timestamp)
            )
            conn.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
        finally:
            conn.close()

    return render_template("register.html")


# ── Logout ────────────────────────────────────────────────────────────────────
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    """Show analytics stats and recent uploads."""
    user_id = session["user_id"]
    conn    = get_db()

    # Total distinct file names (files) uploaded by user
    total_files = conn.execute(
        "SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    # Total version records
    total_versions = conn.execute(
        "SELECT COUNT(*) FROM files WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0]

    # Total storage used
    total_storage_bytes = conn.execute(
        "SELECT SUM(file_size) FROM files WHERE user_id = ?",
        (user_id,)
    ).fetchone()[0] or 0
    
    if total_storage_bytes >= 1024 * 1024:
        total_storage = f"{total_storage_bytes / (1024 * 1024):.2f} MB"
    elif total_storage_bytes >= 1024:
        total_storage = f"{total_storage_bytes / 1024:.2f} KB"
    else:
        total_storage = f"{total_storage_bytes} B"

    # File types analysis
    file_names = conn.execute(
        "SELECT original_name FROM files WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    
    file_types = {}
    for row in file_names:
        name = row[0]
        if '.' in name:
            ext = name.rsplit('.', 1)[-1].lower()
        else:
            ext = 'unknown'
        file_types[ext] = file_types.get(ext, 0) + 1

    # 10 most recent uploads
    recent = conn.execute(
        """SELECT id, original_name, version, timestamp
           FROM files
           WHERE user_id = ?
           ORDER BY id DESC
           LIMIT 10""",
        (user_id,)
    ).fetchall()

    # Fetch all folders for upload destination selection
    folders = conn.execute(
        "SELECT id, name FROM folders WHERE user_id = ? ORDER BY name",
        (user_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_files=total_files,
        total_versions=total_versions,
        total_storage=total_storage,
        file_types=file_types,
        recent=recent,
        folders=folders
    )
# ── Admin Dashboard ───────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
def admin_dashboard():
    """Show global system analytics."""
    if session.get("role") != "admin":
        flash("Access denied. Admin only.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db()

    # Total users
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Total files (all users)
    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    # Total storage used (all users)
    total_storage_bytes = conn.execute("SELECT SUM(file_size) FROM files").fetchone()[0] or 0
    
    if total_storage_bytes >= 1024 * 1024:
        total_storage = f"{total_storage_bytes / (1024 * 1024):.2f} MB"
    elif total_storage_bytes >= 1024:
        total_storage = f"{total_storage_bytes / 1024:.2f} KB"
    else:
        total_storage = f"{total_storage_bytes} B"

    # 10 most recent uploads globally
    recent = conn.execute(
        """SELECT f.id, f.original_name, f.version, f.timestamp, u.username
           FROM files f
           JOIN users u ON f.user_id = u.id
           ORDER BY f.id DESC
           LIMIT 10"""
    ).fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_files=total_files,
        total_storage=total_storage,
        recent=recent
    )


# ── Folders ───────────────────────────────────────────────────────────────────

@app.route("/create_folder", methods=["POST"])
@login_required
def create_folder():
    user_id = session["user_id"]
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id")
    
    if parent_id == "" or parent_id == "None":
        parent_id = None
        
    if not name:
        flash("Folder name cannot be empty.", "danger")
        return redirect(url_for("files", folder_id=parent_id))
        
    conn = get_db()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO folders (name, parent_id, user_id, created_at) VALUES (?, ?, ?, ?)",
        (name, parent_id, user_id, timestamp)
    )
    conn.commit()
    conn.close()
    
    flash(f"Folder '{name}' created.", "success")
    return redirect(url_for("files", folder_id=parent_id))

@app.route("/rename_folder/<int:folder_id>", methods=["POST"])
@login_required
def rename_folder(folder_id):
    user_id = session["user_id"]
    new_name = request.form.get("name", "").strip()
    
    if not new_name:
        flash("Folder name cannot be empty.", "danger")
        return redirect(request.referrer or url_for("files"))
        
    conn = get_db()
    row = conn.execute("SELECT parent_id FROM folders WHERE id = ? AND user_id = ?", (folder_id, user_id)).fetchone()
    if row:
        conn.execute("UPDATE folders SET name = ? WHERE id = ? AND user_id = ?", (new_name, folder_id, user_id))
        conn.commit()
        flash("Folder renamed.", "success")
    else:
        flash("Folder not found.", "danger")
    conn.close()
    
    return redirect(request.referrer or url_for("files"))

@app.route("/delete_folder/<int:folder_id>", methods=["POST"])
@login_required
def delete_folder(folder_id):
    user_id = session["user_id"]
    conn = get_db()
    
    row = conn.execute("SELECT parent_id FROM folders WHERE id = ? AND user_id = ?", (folder_id, user_id)).fetchone()
    if not row:
        conn.close()
        flash("Folder not found.", "danger")
        return redirect(request.referrer or url_for("files"))
        
    parent_id = row["parent_id"]
    
    # Check if empty
    sub_folders = conn.execute("SELECT COUNT(*) FROM folders WHERE parent_id = ?", (folder_id,)).fetchone()[0]
    sub_files = conn.execute("SELECT COUNT(*) FROM files WHERE folder_id = ?", (folder_id,)).fetchone()[0]
    
    if sub_folders > 0 or sub_files > 0:
        conn.close()
        flash("Cannot delete folder: It is not empty.", "danger")
        return redirect(request.referrer or url_for("files"))
        
    conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    conn.commit()
    conn.close()
    
    flash("Folder deleted.", "success")
    return redirect(url_for("files", folder_id=parent_id))


# ── Files list ────────────────────────────────────────────────────────────────
@app.route("/files")
@login_required
def files():
    """Show all files with version history for the logged-in user."""
    user_id = session["user_id"]
    folder_id = request.args.get("folder_id")
    if folder_id == "None" or folder_id == "":
        folder_id = None
        
    conn = get_db()

    # Get breadcrumbs
    breadcrumbs = []
    if folder_id:
        breadcrumbs = get_folder_path_list(folder_id, conn)
        
    # Get subfolders
    if folder_id:
        subfolders = conn.execute("SELECT * FROM folders WHERE parent_id = ? AND user_id = ? ORDER BY name", (folder_id, user_id)).fetchall()
    else:
        subfolders = conn.execute("SELECT * FROM folders WHERE parent_id IS NULL AND user_id = ? ORDER BY name", (user_id,)).fetchall()

    # Get latest version row per original_name (for the summary row)
    if folder_id:
        summary_query = """SELECT original_name,
                  MAX(version)   AS latest_version,
                  MAX(timestamp) AS last_modified,
                  COUNT(*)       AS total_versions,
                  MAX(is_starred) AS is_starred
           FROM files
           WHERE user_id = ? AND folder_id = ? AND is_deleted = 0
           GROUP BY original_name
           ORDER BY is_starred DESC, last_modified DESC"""
        summary_params = (user_id, folder_id)
        
        all_versions_query = """SELECT id, original_name, supabase_path, version, timestamp, is_starred
               FROM files
               WHERE user_id = ? AND folder_id = ? AND is_deleted = 0
               ORDER BY original_name, version DESC"""
        all_versions_params = (user_id, folder_id)
    else:
        summary_query = """SELECT original_name,
                  MAX(version)   AS latest_version,
                  MAX(timestamp) AS last_modified,
                  COUNT(*)       AS total_versions,
                  MAX(is_starred) AS is_starred
           FROM files
           WHERE user_id = ? AND folder_id IS NULL AND is_deleted = 0
           GROUP BY original_name
           ORDER BY is_starred DESC, last_modified DESC"""
        summary_params = (user_id,)
        
        all_versions_query = """SELECT id, original_name, supabase_path, version, timestamp, is_starred
               FROM files
               WHERE user_id = ? AND folder_id IS NULL AND is_deleted = 0
               ORDER BY original_name, version DESC"""
        all_versions_params = (user_id,)


    summary = conn.execute(summary_query, summary_params).fetchall()
    all_versions = conn.execute(all_versions_query, all_versions_params).fetchall()

    conn.close()

    # Build a dict: original_name → list of version rows
    versions_map: dict = {}
    for row in all_versions:
        versions_map.setdefault(row["original_name"], []).append(dict(row))

    return render_template(
        "files.html",
        summary=summary,
        versions_map=versions_map,
        subfolders=subfolders,
        breadcrumbs=breadcrumbs,
        current_folder_id=folder_id
    )


# ── Upload ────────────────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    """
    Accept a file via AJAX multipart POST.
    - Determine next version number for this filename + user.
    - Upload bytes to Supabase under a unique path.
    - Record metadata in SQLite.
    - Return JSON so the dashboard JS can update the UI.
    """
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file part"}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"success": False, "error": "No file selected"}), 400

    user_id       = session["user_id"]
    original_name = secure_filename(f.filename)
    file_bytes    = f.read()
    folder_id_str = request.form.get("folder_id")
    folder_id     = int(folder_id_str) if folder_id_str and folder_id_str != "None" else None

    # Calculate SHA-256 hash of the file
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    conn = get_db()

    # Check for duplicate file upload (same user, filename, and content hash)
    duplicate = conn.execute(
        "SELECT id FROM files WHERE user_id = ? AND original_name = ? AND file_hash = ?",
        (user_id, original_name, file_hash)
    ).fetchone()

    if duplicate:
        conn.close()
        return jsonify({"success": False, "error": "File already exists. No changes detected."}), 400

    # Next version number for this file name
    existing = conn.execute(
        "SELECT MAX(version) FROM files WHERE user_id = ? AND original_name = ?",
        (user_id, original_name)
    ).fetchone()[0]
    version = (existing or 0) + 1

    # Unique Supabase storage path: user_id/folder_path/uuid_originalname
    unique_id     = uuid.uuid4().hex[:8]
    folder_path   = get_supabase_folder_path(folder_id, conn)
    if folder_path:
        supabase_path = f"{user_id}/{folder_path}/{unique_id}_v{version}_{original_name}"
    else:
        supabase_path = f"{user_id}/{unique_id}_v{version}_{original_name}"

    if not supabase:
        conn.close()
        return jsonify({"success": False, "error": "Supabase storage is not connected. Please check your API keys."}), 500

    # Upload to Supabase Storage
    try:
        supabase.storage.from_(BUCKET_NAME).upload(
            path=supabase_path,
            file=file_bytes,
            file_options={"content-type": f.content_type or "application/octet-stream"}
        )
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 500

    # Save metadata
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_size = len(file_bytes)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
    )
    file_id = cur.lastrowid
    
    # Logging is now handled by log_activity and log_recent_activity below
    conn.commit()
    conn.close()

    # Use new helper functions
    log_activity(user_id, "upload", original_name, version, folder_id)
    log_recent_activity(user_id, file_id, "upload")


    return jsonify({
        "success":       True,
        "filename":      original_name,
        "version":       version,
        "timestamp":     timestamp
    })


# ── Download ──────────────────────────────────────────────────────────────────
@app.route("/download/<int:file_id>")
@login_required
def download(file_id):
    """Stream a file from Supabase back to the browser."""
    user_id = session["user_id"]
    conn    = get_db()
    row     = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id)
    ).fetchone()
    conn.close()

    if not row:
        flash("File not found.", "danger")
        return redirect(url_for("files"))

    if not supabase:
        flash("Supabase storage is not connected. Please check your API keys.", "danger")
        return redirect(url_for("files"))

    try:
        # Download bytes from Supabase
        data = supabase.storage.from_(BUCKET_NAME).download(row["supabase_path"])
    except Exception as e:
        flash(f"Download failed: {e}", "danger")
        return redirect(url_for("files"))

    # Write to a temp file and send it
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_" + row["original_name"])
    tmp.write(data)
    tmp.flush()
    tmp.close()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    # Handled by log_activity below
    conn.commit()
    conn.close()

    log_activity(user_id, "download", row["original_name"], row["version"])
    log_recent_activity(user_id, file_id, "download")

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=row["original_name"]
    )


# ── Preview ───────────────────────────────────────────────────────────────────
@app.route("/preview/<int:file_id>")
@login_required
def preview(file_id):
    """Serve a file for in-app previewing without forcing download."""
    user_id = session["user_id"]
    conn    = get_db()
    row     = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id)
    ).fetchone()
    conn.close()

    if not row:
        return "File not found", 404

    if not supabase:
        return "Supabase storage is not connected", 500

    try:
        # Download bytes from Supabase
        data = supabase.storage.from_(BUCKET_NAME).download(row["supabase_path"])
    except Exception as e:
        return f"Preview failed: {e}", 500

    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(row["original_name"])
    if not mime_type:
        mime_type = "application/octet-stream"

    # Write to a temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_" + row["original_name"])
    tmp.write(data)
    tmp.flush()
    tmp.close()

    # Log activity for preview
    log_activity(user_id, "preview", row["original_name"], row["version"])
    log_recent_activity(user_id, file_id, "preview")

    return send_file(
        tmp.name,
        mimetype=mime_type,
        as_attachment=False
    )


# ── Restore ───────────────────────────────────────────────────────────────────
@app.route("/restore/<int:file_id>", methods=["GET", "POST"])
@login_required
def restore(file_id):
    """
    Re-upload an older version as the newest version.
    Downloads the old version bytes from Supabase and re-uploads with version+1.
    """
    user_id = session["user_id"]
    conn    = get_db()
    row     = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id)
    ).fetchone()

    if not row:
        conn.close()
        flash("File not found.", "danger")
        return redirect(url_for("files"))

    original_name = row["original_name"]
    folder_id     = row["folder_id"]

    # Determine next version
    latest = conn.execute(
        "SELECT MAX(version) FROM files WHERE user_id = ? AND original_name = ?",
        (user_id, original_name)
    ).fetchone()[0]
    new_version = (latest or 0) + 1

    if not supabase:
        conn.close()
        flash("Supabase storage is not connected. Please check your API keys.", "danger")
        return redirect(url_for("files"))

    try:
        # Download old bytes
        data = supabase.storage.from_(BUCKET_NAME).download(row["supabase_path"])
        file_hash = hashlib.sha256(data).hexdigest()

        # New unique path
        unique_id     = uuid.uuid4().hex[:8]
        folder_path   = get_supabase_folder_path(folder_id, conn)
        if folder_path:
            new_path  = f"{user_id}/{folder_path}/{unique_id}_v{new_version}_{original_name}"
        else:
            new_path  = f"{user_id}/{unique_id}_v{new_version}_{original_name}"
        
        guessed_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"

        supabase.storage.from_(BUCKET_NAME).upload(
            path=new_path,
            file=data,
            file_options={"content-type": guessed_type}
        )
    except Exception as e:
        print(f"[ERROR] Supabase upload failed during restore: {e}")
        conn.close()
        flash(f"Restore failed: {e}", "danger")
        return redirect(url_for("files"))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_size = len(data)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (original_name, new_path, new_version, timestamp, user_id, file_hash, file_size, folder_id)
    )
    new_file_id = cur.lastrowid

    # Logging is now handled by log_activity below
    conn.commit()
    conn.close()

    log_activity(user_id, "restore", original_name, new_version, folder_id)
    log_recent_activity(user_id, new_file_id, "restore")

    flash(f"Restored '{original_name}' as version {new_version}.", "success")
    return redirect(url_for("files", folder_id=folder_id))


# ── Delete ────────────────────────────────────────────────────────────────────
@app.route("/delete/<int:file_id>", methods=["POST"])
@login_required
def delete(file_id):
    """Delete a specific version from Supabase and from the DB."""
    user_id = session["user_id"]
    conn    = get_db()
    row     = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id)
    ).fetchone()
    
    folder_id = row["folder_id"] if row else None

    if not row:
        conn.close()
        flash("File not found.", "danger")
        return redirect(url_for("files", folder_id=folder_id))

    # Soft Delete: update is_deleted flag and timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE files SET is_deleted = 1, deleted_at = ? WHERE id = ?",
        (timestamp, file_id)
    )
    
    # Handled by log_activity below
    conn.commit()
    conn.close()

    log_activity(user_id, "delete", row["original_name"], row["version"], folder_id)
    # Note: we don't necessarily log 'delete' in recent_activity unless it's a recent interaction?
    # Actually, the user's prompt says: "recently opened/uploaded/restored". 
    # Delete is usually not in "Recent" files view, but it is in "Activity".
    
    flash(f"Version {row['version']} of '{row['original_name']}' moved to Trash.", "success")
    return redirect(url_for("files", folder_id=folder_id))

@app.route("/trash/restore/<int:file_id>", methods=["POST"])
@login_required
def restore_from_trash(file_id):
    """Restore a soft-deleted file."""
    user_id = session["user_id"]
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)).fetchone()
    
    if not row:
        conn.close()
        flash("File not found.", "danger")
        return redirect(url_for("trash"))
        
    conn.execute("UPDATE files SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    
    log_activity(user_id, "restore_from_trash", row["original_name"], row["version"])
    log_recent_activity(user_id, file_id, "restore")
    
    flash(f"'{row['original_name']}' (v{row['version']}) restored from Trash.", "success")
    return redirect(url_for("trash"))

@app.route("/trash/delete/<int:file_id>", methods=["POST"])
@login_required
def permanent_delete(file_id):
    """Permanently delete a file from Supabase and DB."""
    user_id = session["user_id"]
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)).fetchone()
    
    if not row:
        conn.close()
        flash("File not found.", "danger")
        return redirect(url_for("trash"))
        
    if supabase:
        try:
            supabase.storage.from_(BUCKET_NAME).remove([row["supabase_path"]])
        except Exception as e:
            print(f"[WARN] Supabase permanent delete error: {e}")
            # We continue DB deletion even if storage fails to avoid orphaned metadata if storage was already gone
            
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    
    log_activity(user_id, "permanent_delete", row["original_name"], row["version"])
    
    flash(f"'{row['original_name']}' (v{row['version']}) permanently deleted.", "success")
    return redirect(url_for("trash"))

@app.route("/trash/empty", methods=["POST"])
@login_required
def empty_trash():
    """Permanently delete all files in Trash for the current user."""
    user_id = session["user_id"]
    conn = get_db()
    rows = conn.execute("SELECT * FROM files WHERE user_id = ? AND is_deleted = 1", (user_id,)).fetchall()
    
    paths_to_remove = [row["supabase_path"] for row in rows]
    
    if paths_to_remove and supabase:
        try:
            supabase.storage.from_(BUCKET_NAME).remove(paths_to_remove)
        except Exception as e:
            print(f"[WARN] Empty trash Supabase error: {e}")
            
    conn.execute("DELETE FROM files WHERE user_id = ? AND is_deleted = 1", (user_id,))
    conn.commit()
    conn.close()
    
    log_activity(user_id, "empty_trash")
    
    flash("Trash bin emptied.", "success")
    return redirect(url_for("trash"))



@app.route("/recent")
@login_required
def recent():
    """Show recently uploaded/previewed/downloaded/restored files."""
    user_id = session["user_id"]
    conn = get_db()
    # Join with files to get current metadata
    recent_files = conn.execute("""
        SELECT r.action, r.timestamp, f.id, f.original_name, f.version, f.folder_id, f.is_starred
        FROM recent_activity r
        JOIN files f ON r.file_id = f.id
        WHERE r.user_id = ? AND f.is_deleted = 0
        ORDER BY r.timestamp DESC
        LIMIT 50
    """, (user_id,)).fetchall()
    conn.close()
    return render_template("recent.html", recent_files=recent_files)

@app.route("/trash")
@login_required
def trash():
    """Show soft-deleted files."""
    user_id = session["user_id"]
    conn = get_db()
    deleted_files = conn.execute("""
        SELECT * FROM files 
        WHERE user_id = ? AND is_deleted = 1 
        ORDER BY deleted_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return render_template("trash.html", deleted_files=deleted_files)

@app.route("/starred")
@login_required
def starred():
    """Show starred/favorite files."""
    user_id = session["user_id"]
    conn = get_db()
    starred_files = conn.execute("""
        SELECT * FROM files 
        WHERE user_id = ? AND is_starred = 1 AND is_deleted = 0
        ORDER BY timestamp DESC
    """, (user_id,)).fetchall()
    conn.close()
    return render_template("starred.html", starred_files=starred_files)

@app.route("/toggle_star/<int:file_id>", methods=["POST"])
@login_required
def toggle_star(file_id):
    """AJAX endpoint to toggle starred status of a file."""
    user_id = session["user_id"]
    conn = get_db()
    row = conn.execute("SELECT is_starred, original_name FROM files WHERE id = ? AND user_id = ?", (file_id, user_id)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "File not found"}), 404
        
    new_status = 1 if row["is_starred"] == 0 else 0
    # Update all versions of the same file name? Or just this specific version?
    # Usually in Drive/Dropbox, "starring" a file applies to the file object itself.
    # Since we use versioning, let's update all versions for consistency if they share the same original_name?
    # Or just this specific record. Let's do all versions for a better UX.
    conn.execute("UPDATE files SET is_starred = ? WHERE user_id = ? AND original_name = ?", (new_status, user_id, row["original_name"]))
    conn.commit()
    conn.close()
    
    action = "starred" if new_status == 1 else "unstarred"
    log_activity(user_id, action, row["original_name"])
    
    return jsonify({"success": True, "is_starred": new_status})

@app.route("/activity")
@login_required
def activity():
    """Show professional activity timeline."""
    user_id = session["user_id"]
    conn = get_db()
    activities = conn.execute("""
        SELECT * FROM activity_log 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 100
    """, (user_id,)).fetchall()
    conn.close()
    return render_template("activity.html", activities=activities)

@app.route("/analytics")
@login_required
def analytics():
    """Show storage analytics and trends."""
    user_id = session["user_id"]
    conn = get_db()
    
    # Storage breakdown by type
    files = conn.execute("SELECT original_name, file_size FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchall()
    
    stats = {
        "images": 0, "videos": 0, "docs": 0, "others": 0, "total_size": 0,
        "types_count": {"Images": 0, "Videos": 0, "Documents": 0, "Others": 0}
    }
    
    for f in files:
        stats["total_size"] += f["file_size"]
        ext = f["original_name"].split('.')[-1].lower() if '.' in f["original_name"] else ""
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']:
            stats["types_count"]["Images"] += 1
        elif ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
            stats["types_count"]["Videos"] += 1
        elif ext in ['pdf', 'doc', 'docx', 'txt', 'ppt', 'pptx', 'xls', 'xlsx']:
            stats["types_count"]["Documents"] += 1
        else:
            stats["types_count"]["Others"] += 1
            
    # Calculate usage percentage (of 100MB quota)
    stats["usage_pct"] = round(min(100, (stats["total_size"] / (100 * 1024 * 1024)) * 100), 2)
            
    # Upload trends (last 7 days)
    # This is a bit more complex with raw SQL but we can group by date
    trends = conn.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as count 
        FROM activity_log 
        WHERE user_id = ? AND action = 'upload' 
        AND timestamp >= date('now', '-7 days')
        GROUP BY DATE(timestamp)
        ORDER BY date ASC
    """, (user_id,)).fetchall()
    
    trend_data = {t["date"]: t["count"] for t in trends}
    
    # Duplicate savings
    total_versions = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchone()[0]
    unique_files = conn.execute("SELECT COUNT(DISTINCT file_hash) FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchone()[0]
    
    # Previews count
    previews = conn.execute("SELECT COUNT(*) FROM activity_log WHERE user_id = ? AND action = 'preview'", (user_id,)).fetchone()[0]
    
    # Total folders
    folders = conn.execute("SELECT COUNT(*) FROM folders WHERE user_id = ?", (user_id,)).fetchone()[0]
    
    conn.close()
    
    return render_template("analytics.html", 
                           stats=stats, 
                           trend_data=trend_data, 
                           total_versions=total_versions, 
                           unique_files=unique_files,
                           previews=previews,
                           folders=folders)

# ── AI Chat ───────────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    """Handle chat messages to the AI assistant."""
    data = request.get_json()
    message = data.get("message", "")
    
    if not message:
        return jsonify({"success": False, "error": "No message provided."})
        
    user_id = session["user_id"]
    conn = get_db()
    
    total_files = conn.execute("SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = ?", (user_id,)).fetchone()[0]
    total_versions = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)).fetchone()[0]
    total_storage_bytes = conn.execute("SELECT SUM(file_size) FROM files WHERE user_id = ?", (user_id,)).fetchone()[0] or 0
    
    # Fetch recent activity
    try:
        recent_logs = conn.execute(
            "SELECT action, file_name, version, timestamp FROM activity_log WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5",
            (user_id,)
        ).fetchall()
        recent_activity = [dict(row) for row in recent_logs]
    except sqlite3.OperationalError:
        # Table might not exist if init_db wasn't run recently
        recent_activity = []
        
    total_folders = conn.execute("SELECT COUNT(*) FROM folders WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    
    if total_storage_bytes >= 1024 * 1024:
        total_storage = f"{total_storage_bytes / (1024 * 1024):.2f} MB"
    elif total_storage_bytes >= 1024:
        total_storage = f"{total_storage_bytes / 1024:.2f} KB"
    else:
        total_storage = f"{total_storage_bytes} B"
        
    context_stats = {
        "total_files": total_files,
        "total_versions": total_versions,
        "total_storage": total_storage,
        "total_folders": total_folders,
        "recent_activity": recent_activity
    }
    
    ai_response = ask_ai(message, context_stats)
    
    return jsonify({
        "success": True,
        "response": ai_response
    })

@app.route("/settings")
@login_required
def settings():
    """Show professional user settings and metrics."""
    user_id = session["user_id"]
    conn = get_db()
    
    # User Profile
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    
    # Last Login
    last_login_row = conn.execute(
        "SELECT timestamp FROM activity_log WHERE user_id = ? AND action = 'login' ORDER BY timestamp DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    last_login = last_login_row["timestamp"] if last_login_row else "No record found"
    
    # Storage Metrics
    total_files = conn.execute("SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchone()[0]
    total_versions = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchone()[0]
    total_folders = conn.execute("SELECT COUNT(*) FROM folders WHERE user_id = ?", (user_id,)).fetchone()[0]
    
    total_bytes = conn.execute("SELECT SUM(file_size) FROM files WHERE user_id = ? AND is_deleted = 0", (user_id,)).fetchone()[0] or 0
    unique_bytes = conn.execute("SELECT SUM(min_size) FROM (SELECT MIN(file_size) as min_size FROM files WHERE user_id = ? AND is_deleted = 0 GROUP BY file_hash)", (user_id,)).fetchone()[0] or 0
    savings_bytes = total_bytes - unique_bytes
    
    # Format sizes
    def format_size(b):
        if b >= 1024 * 1024: return f"{b / (1024 * 1024):.2f} MB"
        if b >= 1024: return f"{b / 1024:.2f} KB"
        return f"{b} B"

    storage_stats = {
        "files": total_files,
        "versions": total_versions,
        "folders": total_folders,
        "used": format_size(total_bytes),
        "savings": format_size(savings_bytes)
    }
    
    conn.close()
    return render_template("settings.html", user=user, last_login=last_login, storage_stats=storage_stats)

@app.route("/update_profile", methods=["POST"])
@login_required
def update_profile():
    """Handle username and profile picture updates."""
    user_id = session["user_id"]
    username = request.form.get("username", "").strip()
    avatar_file = request.files.get("avatar")
    
    if not username:
        return jsonify({"success": False, "error": "Username cannot be empty."}), 400
        
    conn = get_db()
    try:
        # Check if username is taken by someone else
        existing = conn.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id)).fetchone()
        if existing:
            conn.close()
            return jsonify({"success": False, "error": "Username is already taken."}), 400
            
        avatar_filename = None
        if avatar_file and avatar_file.filename != "":
            # Validate extension
            ext = avatar_file.filename.rsplit(".", 1)[-1].lower()
            if ext not in ["png", "jpg", "jpeg", "webp"]:
                conn.close()
                return jsonify({"success": False, "error": "Invalid file type. Use PNG, JPG, or WEBP."}), 400
                
            # Secure filename and save
            unique_id = uuid.uuid4().hex[:8]
            avatar_filename = f"avatar_{user_id}_{unique_id}.{ext}"
            
            # Ensure directory exists
            upload_dir = os.path.join("static", "uploads", "profile")
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)
                
            avatar_file.save(os.path.join(upload_dir, avatar_filename))
            
            # Update DB with new avatar
            conn.execute("UPDATE users SET username = ?, avatar = ? WHERE id = ?", (username, avatar_filename, user_id))
            session["avatar"] = avatar_filename
        else:
            # Update only username
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
            
        conn.commit()
        session["username"] = username
        
        # Log activity
        log_activity(user_id, "update_profile", "Account Profile")
        
        return jsonify({
            "success": True, 
            "message": "Profile updated successfully!",
            "username": username,
            "avatar": session.get("avatar")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # In development, run with debug=True on port 5000
    # In production, Gunicorn will handle the startup
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
