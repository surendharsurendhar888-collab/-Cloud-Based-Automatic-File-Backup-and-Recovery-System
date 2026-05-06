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
from dotenv import dotenv_values
import google.generativeai as genai

# ─── Environment Setup ────────────────────────────────────────────────────────
env_config = dotenv_values(".env")
GEMINI_API_KEY = env_config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ─── Supabase client ────────────────────────────────────────────────────────
from supabase import create_client, Client

SUPABASE_URL = env_config.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_KEY = env_config.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
BUCKET_NAME  = "files"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[WARNING] Supabase credentials missing. Ensure SUPABASE_URL and SUPABASE_KEY are in your .env file.")

# Create Supabase client (supabase-py 2.x accepts the publishable key directly)
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
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

    # --- Admin user creation logic added here ---
    admin_user = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not admin_user:
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", hash_password("admin123"), "admin")
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

def ask_ai(message, context_stats):
    """Query Gemini API with context about the user's storage."""
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY is not configured in the backend."
        
    system_prompt = f"""You are CloudShield AI, a helpful, professional, and smart AI assistant integrated into a modern cloud backup system.
    
Here are the user's current storage statistics:
- Total Files: {context_stats['total_files']}
- Total Versions: {context_stats['total_versions']}
- Storage Used: {context_stats['total_storage']}

Be helpful, concise, and use markdown formatting where appropriate.
If they ask about duplicate prevention, explain that the system calculates a SHA-256 hash for every file uploaded to guarantee duplicates aren't stored twice.
If they ask about file recovery, explain that they can view their file versions and restore any previous version using the 'My Files' tab.
"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-lite', system_instruction=system_prompt)
        response = model.generate_content(message)
        return response.text
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

# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Redirect to dashboard if logged in, else login."""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


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
            except IndexError:
                session["role"] = "user"

            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html")


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
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, hash_password(password))
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

    conn.close()

    return render_template(
        "dashboard.html",
        total_files=total_files,
        total_versions=total_versions,
        total_storage=total_storage,
        file_types=file_types,
        recent=recent
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


# ── Files list ────────────────────────────────────────────────────────────────
@app.route("/files")
@login_required
def files():
    """Show all files with version history for the logged-in user."""
    user_id = session["user_id"]
    conn    = get_db()

    # Get latest version row per original_name (for the summary row)
    summary = conn.execute(
        """SELECT original_name,
                  MAX(version)   AS latest_version,
                  MAX(timestamp) AS last_modified,
                  COUNT(*)       AS total_versions
           FROM files
           WHERE user_id = ?
           GROUP BY original_name
           ORDER BY last_modified DESC""",
        (user_id,)
    ).fetchall()

    # Get ALL version rows so the template can expand them
    all_versions = conn.execute(
        """SELECT id, original_name, supabase_path, version, timestamp
           FROM files
           WHERE user_id = ?
           ORDER BY original_name, version DESC""",
        (user_id,)
    ).fetchall()

    conn.close()

    # Build a dict: original_name → list of version rows
    versions_map: dict = {}
    for row in all_versions:
        versions_map.setdefault(row["original_name"], []).append(dict(row))

    return render_template(
        "files.html",
        summary=summary,
        versions_map=versions_map
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

    # Unique Supabase storage path: user_id/uuid_originalname
    unique_id     = uuid.uuid4().hex[:8]
    supabase_path = f"{user_id}/{unique_id}_v{version}_{original_name}"

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
    conn.execute(
        """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size)
    )
    conn.commit()
    conn.close()

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

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=row["original_name"]
    )


# ── Restore ───────────────────────────────────────────────────────────────────
@app.route("/restore/<int:file_id>")
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

    # Determine next version
    latest = conn.execute(
        "SELECT MAX(version) FROM files WHERE user_id = ? AND original_name = ?",
        (user_id, original_name)
    ).fetchone()[0]
    new_version = (latest or 0) + 1

    try:
        # Download old bytes
        data = supabase.storage.from_(BUCKET_NAME).download(row["supabase_path"])
        file_hash = hashlib.sha256(data).hexdigest()

        # New unique path
        unique_id     = uuid.uuid4().hex[:8]
        new_path      = f"{user_id}/{unique_id}_v{new_version}_{original_name}"

        supabase.storage.from_(BUCKET_NAME).upload(
            path=new_path,
            file=data,
            file_options={"content-type": "application/octet-stream"}
        )
    except Exception as e:
        conn.close()
        flash(f"Restore failed: {e}", "danger")
        return redirect(url_for("files"))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_size = len(data)
    conn.execute(
        """INSERT INTO files (original_name, supabase_path, version, timestamp, user_id, file_hash, file_size)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (original_name, new_path, new_version, timestamp, user_id, file_hash, file_size)
    )
    conn.commit()
    conn.close()

    flash(f"Restored '{original_name}' as version {new_version}.", "success")
    return redirect(url_for("files"))


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

    if not row:
        conn.close()
        flash("File not found.", "danger")
        return redirect(url_for("files"))

    try:
        # Remove from Supabase Storage
        supabase.storage.from_(BUCKET_NAME).remove([row["supabase_path"]])
    except Exception as e:
        # Log but continue — still remove from DB
        print(f"[WARN] Supabase delete error: {e}")

    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

    flash(f"Version {row['version']} of '{row['original_name']}' deleted.", "success")
    return redirect(url_for("files"))


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
        "total_storage": total_storage
    }
    
    ai_response = ask_ai(message, context_stats)
    
    return jsonify({
        "success": True,
        "response": ai_response
    })

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()          # create tables if they don't exist
    app.run(debug=True)
