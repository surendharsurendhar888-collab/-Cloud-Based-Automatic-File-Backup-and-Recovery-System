"""
Cloud Based Automatic File Backup and Recovery System
======================================================
Flask backend with SQLite (metadata) + Supabase Storage (files)
Author: CloudBackup System
"""

import os
import psycopg2
import psycopg2.extras
from psycopg2 import pool
import hashlib
import uuid
import logging
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
import time

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
# Secure session configuration
app.secret_key = env_config.get("SECRET_KEY") or os.environ.get("SECRET_KEY") or "fallback_secret_key_for_dev_only"
app.config.update(
    SESSION_COOKIE_SECURE=env_config.get("SESSION_COOKIE_SECURE", "False") == "True",
    SESSION_COOKIE_HTTPONLY=env_config.get("SESSION_COOKIE_HTTPONLY", "True") == "True",
    SESSION_COOKIE_SAMESITE=env_config.get("SESSION_COOKIE_SAMESITE", "Lax"),
    PERMANENT_SESSION_LIFETIME=86400 * 7 # 1 week
)

# Folders
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR  = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── Database helpers (PostgreSQL) ────────────────────────────────────────────
raw_db_url = env_config.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
DATABASE_URL = raw_db_url.strip('"').strip("'") if raw_db_url else None

# Connection pool for production stability
db_pool = None

def init_pool():
    global db_pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing. PostgreSQL migration requires this to be set.")
    try:
        # psycopg2 doesn't support the pgbouncer=true query parameter, so we strip it if present
        clean_url = DATABASE_URL.split("?")[0] if "?" in DATABASE_URL else DATABASE_URL
        db_pool = pool.SimpleConnectionPool(1, 20, clean_url)
        print("[INFO] PostgreSQL connection pool initialized.")
    except Exception as e:
        raise Exception(f"Could not initialize PostgreSQL pool: {e}")

init_pool()

def get_db():
    """Get a connection from the pool and return it with a DictCursor."""
    global db_pool
    if not db_pool:
        init_pool()
    
    # Simple retry logic for production stability
    for i in range(3):
        try:
            conn = db_pool.getconn()
            # This allows row["column_name"] access like SQLite.Row
            return conn
        except Exception as e:
            print(f"[RETRY {i+1}] Connection error: {e}")
            time.sleep(1)
            init_pool()
    raise Exception("Could not connect to database after multiple retries.")

def release_db(conn):
    if db_pool and conn:
        db_pool.putconn(conn)

def init_db():
    """Create PostgreSQL tables on startup."""
    conn = get_db()
    try:
        cur = conn.cursor()
        
        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                google_id TEXT,
                email TEXT,
                avatar TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Folders table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Files table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY,
                original_name TEXT NOT NULL,
                supabase_path TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                file_hash TEXT,
                file_size BIGINT DEFAULT 0,
                is_deleted SMALLINT DEFAULT 0,
                deleted_at TIMESTAMP,
                is_starred SMALLINT DEFAULT 0
            )
        """)

        # Activity Log table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                file_name TEXT,
                version INTEGER,
                folder_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Recent Activity table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recent_activity (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                action TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Chats table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                message TEXT,
                response TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Starred Files table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS starred_files (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Trash table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trash (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Admin user creation
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "admin")
            )
            print("[INFO] Default admin user created.")
        
        conn.commit()
    except Exception as e:
        print(f"[ERROR] init_db failed: {e}")
        conn.rollback()
    finally:
        release_db(conn)

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



def hash_password(password: str) -> str:
    """SHA-256 hash a password."""
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(user_id, action, file_name=None, version=None, folder_id=None):
    """Log a user action to the activity_log table."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO activity_log (user_id, action, file_name, version, folder_id) VALUES (%s, %s, %s, %s, %s)",
            (user_id, action, file_name, version, folder_id)
        )
        conn.commit()
    finally:
        release_db(conn)

def log_recent_activity(user_id, file_id, action):
    """Update or insert into recent_activity table."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT id FROM recent_activity WHERE user_id = %s AND file_id = %s AND action = %s",
            (user_id, file_id, action)
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                "UPDATE recent_activity SET timestamp = CURRENT_TIMESTAMP WHERE id = %s",
                (existing["id"],)
            )
        else:
            cur.execute(
                "INSERT INTO recent_activity (user_id, file_id, action) VALUES (%s, %s, %s)",
                (user_id, file_id, action)
            )
        conn.commit()
    finally:
        release_db(conn)


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
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        finally:
            release_db(conn)

        if user and user["password"] == hash_password(password):
            # Security: clear session before setting new user data
            session.clear()
            session.permanent = True
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["avatar"] = user["avatar"]

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # Check if user exists by google_id
        cur.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
        user = cur.fetchone()
        
        if not user:
            # Check if user exists by email or username
            cur.execute("SELECT * FROM users WHERE email = %s OR username = %s", (email, username))
            user = cur.fetchone()
            if user:
                # Update existing user with google_id
                cur.execute("UPDATE users SET google_id = %s WHERE id = %s", (google_id, user["id"]))
                conn.commit()
            else:
                # Create new user
                random_pwd = "".join(random.choices(string.ascii_letters + string.digits, k=16))
                hashed_pwd = hash_password(random_pwd)
                try:
                    cur.execute(
                        "INSERT INTO users (username, password, role, google_id, email) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (username, hashed_pwd, "user", google_id, email)
                    )
                    user_id = cur.fetchone()[0]
                    conn.commit()
                    user = {"id": user_id, "username": username, "role": "user", "avatar": None}
                except psycopg2.IntegrityError:
                    conn.rollback()
                    # Fallback if username exists
                    username = f"{username}_{str(uuid.uuid4())[:4]}"
                    cur.execute(
                        "INSERT INTO users (username, password, role, google_id, email) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (username, hashed_pwd, "user", google_id, email)
                    )
                    user_id = cur.fetchone()[0]
                    conn.commit()
                    user = {"id": user_id, "username": username, "role": "user", "avatar": None}
    finally:
        release_db(conn)

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["avatar"] = user.get("avatar")

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
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, hash_password(password))
            )
            conn.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash("Username already exists.", "danger")
        finally:
            release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Total distinct file names (files) uploaded by user
        cur.execute(
            "SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = %s",
            (user_id,)
        )
        total_files = cur.fetchone()[0]

        # Total version records
        cur.execute(
            "SELECT COUNT(*) FROM files WHERE user_id = %s",
            (user_id,)
        )
        total_versions = cur.fetchone()[0]

        # Total storage used
        cur.execute(
            "SELECT SUM(file_size) FROM files WHERE user_id = %s",
            (user_id,)
        )
        total_storage_bytes = cur.fetchone()[0] or 0
        
        if total_storage_bytes >= 1024 * 1024:
            total_storage = f"{total_storage_bytes / (1024 * 1024):.2f} MB"
        elif total_storage_bytes >= 1024:
            total_storage = f"{total_storage_bytes / 1024:.2f} KB"
        else:
            total_storage = f"{total_storage_bytes} B"

        # File types analysis
        cur.execute(
            "SELECT original_name FROM files WHERE user_id = %s",
            (user_id,)
        )
        file_names = cur.fetchall()
        
        file_types = {}
        for row in file_names:
            name = row[0]
            if '.' in name:
                ext = name.rsplit('.', 1)[-1].lower()
            else:
                ext = 'unknown'
            file_types[ext] = file_types.get(ext, 0) + 1

        # 10 most recent uploads
        cur.execute(
            """SELECT id, original_name, version, timestamp
               FROM files
               WHERE user_id = %s
               ORDER BY id DESC
               LIMIT 10""",
            (user_id,)
        )
        recent = cur.fetchall()

        # Fetch all folders for upload destination selection
        cur.execute(
            "SELECT id, name FROM folders WHERE user_id = %s ORDER BY name",
            (user_id,)
        )
        folders = cur.fetchall()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Total users
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        # Total files (all users)
        cur.execute("SELECT COUNT(*) FROM files")
        total_files = cur.fetchone()[0]

        # Total storage used (all users)
        cur.execute("SELECT SUM(file_size) FROM files")
        total_storage_bytes = cur.fetchone()[0] or 0
        
        if total_storage_bytes >= 1024 * 1024:
            total_storage = f"{total_storage_bytes / (1024 * 1024):.2f} MB"
        elif total_storage_bytes >= 1024:
            total_storage = f"{total_storage_bytes / 1024:.2f} KB"
        else:
            total_storage = f"{total_storage_bytes} B"

        # 10 most recent uploads globally
        cur.execute(
            """SELECT f.id, f.original_name, f.version, f.timestamp, u.username
               FROM files f
               JOIN users u ON f.user_id = u.id
               ORDER BY f.id DESC
               LIMIT 10"""
        )
        recent = cur.fetchall()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO folders (name, parent_id, user_id) VALUES (%s, %s, %s)",
            (name, parent_id, user_id)
        )
        conn.commit()
    finally:
        release_db(conn)
    
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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT parent_id FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE folders SET name = %s WHERE id = %s AND user_id = %s", (new_name, folder_id, user_id))
            conn.commit()
            flash("Folder renamed.", "success")
        else:
            flash("Folder not found.", "danger")
    finally:
        release_db(conn)
    
    return redirect(request.referrer or url_for("files"))

@app.route("/delete_folder/<int:folder_id>", methods=["POST"])
@login_required
def delete_folder(folder_id):
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT parent_id FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))
        row = cur.fetchone()
        if not row:
            flash("Folder not found.", "danger")
            return redirect(request.referrer or url_for("files"))
            
        parent_id = row["parent_id"]
        
        # Check if empty
        cur.execute("SELECT COUNT(*) FROM folders WHERE parent_id = %s", (folder_id,))
        sub_folders = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM files WHERE folder_id = %s", (folder_id,))
        sub_files = cur.fetchone()[0]
        
        if sub_folders > 0 or sub_files > 0:
            flash("Cannot delete folder: It is not empty.", "danger")
            return redirect(request.referrer or url_for("files"))
            
        cur.execute("DELETE FROM folders WHERE id = %s", (folder_id,))
        conn.commit()
    finally:
        release_db(conn)
    
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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get breadcrumbs
        breadcrumbs = []
        if folder_id:
            breadcrumbs = get_folder_path_list(folder_id, conn)
            
        # Get subfolders
        if folder_id:
            cur.execute("SELECT * FROM folders WHERE parent_id = %s AND user_id = %s ORDER BY name", (folder_id, user_id))
        else:
            cur.execute("SELECT * FROM folders WHERE parent_id IS NULL AND user_id = %s ORDER BY name", (user_id,))
        subfolders = cur.fetchall()

        # Get latest version row per original_name (for the summary row)
        if folder_id:
            summary_query = """SELECT original_name,
                      MAX(version)   AS latest_version,
                      MAX(timestamp) AS last_modified,
                      COUNT(*)       AS total_versions,
                      MAX(is_starred) AS is_starred
               FROM files
               WHERE user_id = %s AND folder_id = %s AND is_deleted = 0
               GROUP BY original_name
               ORDER BY is_starred DESC, last_modified DESC"""
            summary_params = (user_id, folder_id)
            
            all_versions_query = """SELECT id, original_name, supabase_path, version, timestamp, is_starred
                   FROM files
                   WHERE user_id = %s AND folder_id = %s AND is_deleted = 0
                   ORDER BY original_name, version DESC"""
            all_versions_params = (user_id, folder_id)
        else:
            summary_query = """SELECT original_name,
                      MAX(version)   AS latest_version,
                      MAX(timestamp) AS last_modified,
                      COUNT(*)       AS total_versions,
                      MAX(is_starred) AS is_starred
               FROM files
               WHERE user_id = %s AND folder_id IS NULL AND is_deleted = 0
               GROUP BY original_name
               ORDER BY is_starred DESC, last_modified DESC"""
            summary_params = (user_id,)
            
            all_versions_query = """SELECT id, original_name, supabase_path, version, timestamp, is_starred
                   FROM files
                   WHERE user_id = %s AND folder_id IS NULL AND is_deleted = 0
                   ORDER BY original_name, version DESC"""
            all_versions_params = (user_id,)


        cur.execute(summary_query, summary_params)
        summary = cur.fetchall()
        cur.execute(all_versions_query, all_versions_params)
        all_versions = cur.fetchall()
    finally:
        release_db(conn)

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
    - Record metadata in PostgreSQL.
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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Check for duplicate file upload (same user, filename, and content hash)
        cur.execute(
            "SELECT id FROM files WHERE user_id = %s AND original_name = %s AND file_hash = %s",
            (user_id, original_name, file_hash)
        )
        duplicate = cur.fetchone()

        if duplicate:
            return jsonify({"success": False, "error": "File already exists. No changes detected."}), 400

        # Next version number for this file name
        cur.execute(
            "SELECT MAX(version) FROM files WHERE user_id = %s AND original_name = %s",
            (user_id, original_name)
        )
        existing_version = cur.fetchone()[0]
        version = (existing_version or 0) + 1

        # Unique Supabase storage path: user_id/folder_path/uuid_originalname
        unique_id     = uuid.uuid4().hex[:8]
        folder_path   = get_supabase_folder_path(folder_id, conn)
        if folder_path:
            supabase_path = f"{user_id}/{folder_path}/{unique_id}_v{version}_{original_name}"
        else:
            supabase_path = f"{user_id}/{unique_id}_v{version}_{original_name}"

        if not supabase:
            return jsonify({"success": False, "error": "Supabase storage is not connected. Please check your API keys."}), 500

        # Upload to Supabase Storage
        try:
            supabase.storage.from_(BUCKET_NAME).upload(
                path=supabase_path,
                file=file_bytes,
                file_options={"content-type": f.content_type or "application/octet-stream"}
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

        # Save metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_size = len(file_bytes)
        cur.execute(
            """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
        )
        file_id = cur.fetchone()[0]
        conn.commit()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT * FROM files WHERE id = %s AND user_id = %s",
            (file_id, user_id)
        )
        row = cur.fetchone()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT * FROM files WHERE id = %s AND user_id = %s",
            (file_id, user_id)
        )
        row = cur.fetchone()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT * FROM files WHERE id = %s AND user_id = %s",
            (file_id, user_id)
        )
        row = cur.fetchone()

        if not row:
            flash("File not found.", "danger")
            return redirect(url_for("files"))

        original_name = row["original_name"]
        folder_id     = row["folder_id"]

        # Determine next version
        cur.execute(
            "SELECT MAX(version) FROM files WHERE user_id = %s AND original_name = %s",
            (user_id, original_name)
        )
        latest_version = cur.fetchone()[0]
        new_version = (latest_version or 0) + 1

        if not supabase:
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
            flash(f"Restore failed: {e}", "danger")
            return redirect(url_for("files"))

        file_size = len(data)
        cur.execute(
            """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size, folder_id)
               VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s) RETURNING id""",
            (original_name, new_path, new_version, user_id, file_hash, file_size, folder_id)
        )
        new_file_id = cur.fetchone()[0]
        conn.commit()
    finally:
        release_db(conn)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT * FROM files WHERE id = %s AND user_id = %s",
            (file_id, user_id)
        )
        row = cur.fetchone()
        
        if not row:
            flash("File not found.", "danger")
            return redirect(url_for("files"))

        folder_id = row["folder_id"]

        # Soft Delete: update is_deleted flag and timestamp
        cur.execute(
            "UPDATE files SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP WHERE id = %s",
            (file_id,)
        )
        conn.commit()
    finally:
        release_db(conn)

    log_activity(user_id, "delete", row["original_name"], row["version"], folder_id)
    
    flash(f"Version {row['version']} of '{row['original_name']}' moved to Trash.", "success")
    return redirect(url_for("files", folder_id=folder_id))

@app.route("/trash/restore/<int:file_id>", methods=["POST"])
@login_required
def restore_from_trash(file_id):
    """Restore a soft-deleted file."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM files WHERE id = %s AND user_id = %s", (file_id, user_id))
        row = cur.fetchone()
        
        if not row:
            flash("File not found.", "danger")
            return redirect(url_for("trash"))
            
        cur.execute("UPDATE files SET is_deleted = 0, deleted_at = NULL WHERE id = %s", (file_id,))
        conn.commit()
    finally:
        release_db(conn)
    
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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM files WHERE id = %s AND user_id = %s", (file_id, user_id))
        row = cur.fetchone()
        
        if not row:
            flash("File not found.", "danger")
            return redirect(url_for("trash"))
            
        if supabase:
            try:
                supabase.storage.from_(BUCKET_NAME).remove([row["supabase_path"]])
            except Exception as e:
                print(f"[WARN] Supabase permanent delete error: {e}")
                
        cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
        conn.commit()
    finally:
        release_db(conn)
    
    log_activity(user_id, "permanent_delete", row["original_name"], row["version"])
    
    flash(f"'{row['original_name']}' (v{row['version']}) permanently deleted.", "success")
    return redirect(url_for("trash"))

@app.route("/trash/empty", methods=["POST"])
@login_required
def empty_trash():
    """Permanently delete all files in Trash for the current user."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM files WHERE user_id = %s AND is_deleted = 1", (user_id,))
        rows = cur.fetchall()
        
        paths_to_remove = [row["supabase_path"] for row in rows]
        
        if paths_to_remove and supabase:
            try:
                supabase.storage.from_(BUCKET_NAME).remove(paths_to_remove)
            except Exception as e:
                print(f"[WARN] Empty trash Supabase error: {e}")
                
        cur.execute("DELETE FROM files WHERE user_id = %s AND is_deleted = 1", (user_id,))
        conn.commit()
    finally:
        release_db(conn)
    
    log_activity(user_id, "empty_trash")
    
    flash("Trash bin emptied.", "success")
    return redirect(url_for("trash"))



@app.route("/recent")
@login_required
def recent():
    """Show recently uploaded/previewed/downloaded/restored files."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT r.action, r.timestamp, f.id, f.original_name, f.version, f.folder_id, f.is_starred
            FROM recent_activity r
            JOIN files f ON r.file_id = f.id
            WHERE r.user_id = %s AND f.is_deleted = 0
            ORDER BY r.timestamp DESC
            LIMIT 50
        """, (user_id,))
        recent_files = cur.fetchall()
    finally:
        release_db(conn)
    return render_template("recent.html", recent_files=recent_files)

@app.route("/trash")
@login_required
def trash():
    """Show soft-deleted files."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM files 
            WHERE user_id = %s AND is_deleted = 1 
            ORDER BY deleted_at DESC
        """, (user_id,))
        deleted_files = cur.fetchall()
    finally:
        release_db(conn)
    return render_template("trash.html", deleted_files=deleted_files)

@app.route("/starred")
@login_required
def starred():
    """Show starred/favorite files."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM files 
            WHERE user_id = %s AND is_starred = 1 AND is_deleted = 0
            ORDER BY timestamp DESC
        """, (user_id,))
        starred_files = cur.fetchall()
    finally:
        release_db(conn)
    return render_template("starred.html", starred_files=starred_files)

@app.route("/toggle_star/<int:file_id>", methods=["POST"])
@login_required
def toggle_star(file_id):
    """AJAX endpoint to toggle starred status of a file."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT is_starred, original_name FROM files WHERE id = %s AND user_id = %s", (file_id, user_id))
        row = cur.fetchone()
        
        if not row:
            return jsonify({"success": False, "error": "File not found"}), 404
            
        new_status = 1 if row["is_starred"] == 0 else 0
        cur.execute("UPDATE files SET is_starred = %s WHERE user_id = %s AND original_name = %s", (new_status, user_id, row["original_name"]))
        conn.commit()
    finally:
        release_db(conn)
    
    action = "starred" if new_status == 1 else "unstarred"
    log_activity(user_id, action, row["original_name"])
    
    return jsonify({"success": True, "is_starred": new_status})

@app.route("/activity")
@login_required
def activity():
    """Show professional activity timeline."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM activity_log 
            WHERE user_id = %s 
            ORDER BY timestamp DESC 
            LIMIT 100
        """, (user_id,))
        activities = cur.fetchall()
    finally:
        release_db(conn)
    return render_template("activity.html", activities=activities)

@app.route("/analytics")
@login_required
def analytics():
    """Show storage analytics and trends."""
    user_id = session["user_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Storage breakdown by type
        cur.execute("SELECT original_name, file_size FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        files_data = cur.fetchall()
        
        stats = {
            "images": 0, "videos": 0, "docs": 0, "others": 0, "total_size": 0,
            "types_count": {"Images": 0, "Videos": 0, "Documents": 0, "Others": 0}
        }
        
        for f in files_data:
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
                
        # Upload trends (last 7 days) - PostgreSQL syntax
        cur.execute("""
            SELECT CAST(timestamp AS DATE) as date, COUNT(*) as count 
            FROM activity_log 
            WHERE user_id = %s AND action = 'upload' 
            AND timestamp >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY CAST(timestamp AS DATE)
            ORDER BY date ASC
        """, (user_id,))
        trends = cur.fetchall()
        
        trend_data = {str(t["date"]): t["count"] for t in trends}
        
        # Duplicate savings
        cur.execute("SELECT COUNT(*) FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        total_versions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT file_hash) FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        unique_files = cur.fetchone()[0]
        
        # Previews count
        cur.execute("SELECT COUNT(*) FROM activity_log WHERE user_id = %s AND action = 'preview'", (user_id,))
        previews = cur.fetchone()[0]
        
        # Total folders
        cur.execute("SELECT COUNT(*) FROM folders WHERE user_id = %s", (user_id,))
        folders_count = cur.fetchone()[0]
    finally:
        release_db(conn)
    
    return render_template("analytics.html", 
                           stats=stats, 
                           trend_data=trend_data, 
                           total_versions=total_versions, 
                           unique_files=unique_files,
                           previews=previews,
                           folders=folders_count)

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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cur.execute("SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = %s", (user_id,))
        total_files = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM files WHERE user_id = %s", (user_id,))
        total_versions = cur.fetchone()[0]
        cur.execute("SELECT SUM(file_size) FROM files WHERE user_id = %s", (user_id,))
        total_storage_bytes = cur.fetchone()[0] or 0
        
        # Fetch recent activity
        cur.execute(
            "SELECT action, file_name, version, timestamp FROM activity_log WHERE user_id = %s ORDER BY timestamp DESC LIMIT 5",
            (user_id,)
        )
        recent_logs = cur.fetchall()
        recent_activity = [dict(row) for row in recent_logs]
            
        cur.execute("SELECT COUNT(*) FROM folders WHERE user_id = %s", (user_id,))
        total_folders = cur.fetchone()[0]
    finally:
        release_db(conn)
    
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
    
    # Log to chats table
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chats (user_id, message, response) VALUES (%s, %s, %s)",
            (user_id, message, ai_response)
        )
        conn.commit()
    finally:
        release_db(conn)
    
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
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # User Profile
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        
        # Last Login
        cur.execute(
            "SELECT timestamp FROM activity_log WHERE user_id = %s AND action = 'login' ORDER BY timestamp DESC LIMIT 1",
            (user_id,)
        )
        last_login_row = cur.fetchone()
        last_login = last_login_row["timestamp"] if last_login_row else "No record found"
        
        # Storage Metrics
        cur.execute("SELECT COUNT(DISTINCT original_name) FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        total_files = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        total_versions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM folders WHERE user_id = %s", (user_id,))
        total_folders = cur.fetchone()[0]
        
        cur.execute("SELECT SUM(file_size) FROM files WHERE user_id = %s AND is_deleted = 0", (user_id,))
        total_bytes = cur.fetchone()[0] or 0
        cur.execute("SELECT SUM(min_size) FROM (SELECT MIN(file_size) as min_size FROM files WHERE user_id = %s AND is_deleted = 0 GROUP BY file_hash) as sub", (user_id,))
        unique_bytes = cur.fetchone()[0] or 0
        savings_bytes = total_bytes - unique_bytes
    finally:
        release_db(conn)
    
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
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # Check if username is taken by someone else
        cur.execute("SELECT id FROM users WHERE username = %s AND id != %s", (username, user_id))
        existing = cur.fetchone()
        if existing:
            return jsonify({"success": False, "error": "Username is already taken."}), 400
            
        avatar_filename = None
        if avatar_file and avatar_file.filename != "":
            # Validate extension
            ext = avatar_file.filename.rsplit(".", 1)[-1].lower()
            if ext not in ["png", "jpg", "jpeg", "webp"]:
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
            cur.execute("UPDATE users SET username = %s, avatar = %s WHERE id = %s", (username, avatar_filename, user_id))
            session["avatar"] = avatar_filename
        else:
            # Update only username
            cur.execute("UPDATE users SET username = %s WHERE id = %s", (username, user_id))
            
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
        release_db(conn)

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # In development, run with debug=True on port 5000
    # In production, Gunicorn will handle the startup
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
