import os
import time
import hashlib
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import dotenv_values

# ─── Environment Setup ────────────────────────────────────────────────────────
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(UTILS_DIR)
env_config = dotenv_values(os.path.join(PROJECT_DIR, ".env"))

raw_db_url = env_config.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
if raw_db_url:
    raw_db_url = raw_db_url.strip()
    if raw_db_url.startswith("DATABASE_URL="):
        raw_db_url = raw_db_url.split("=", 1)[1]
    DATABASE_URL = raw_db_url.strip('"').strip("'")
else:
    DATABASE_URL = None

db_pool = None

def init_pool():
    global db_pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is missing. PostgreSQL migration requires this to be set.")
    try:
        clean_url = DATABASE_URL.split("?")[0] if "?" in DATABASE_URL else DATABASE_URL
        db_pool = pool.SimpleConnectionPool(1, 20, clean_url)
        print("[INFO] PostgreSQL connection pool initialized.")
    except Exception as e:
        raise Exception(f"Could not initialize PostgreSQL pool: {e}")

# Self initialize pool when imported
init_pool()

def get_db():
    """Get a connection from the pool and return it."""
    global db_pool
    if not db_pool:
        init_pool()
    
    for i in range(3):
        try:
            conn = db_pool.getconn()
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

        # Ensure older users table instances have modern columns
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT")

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

        # Ensure older folders and files table instances have modern columns
        cur.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS file_hash TEXT")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS file_size BIGINT DEFAULT 0")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS is_deleted SMALLINT DEFAULT 0")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS is_starred SMALLINT DEFAULT 0")
        cur.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE")

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

        # Ensure older activity_log table instances have modern columns
        cur.execute("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS folder_id INTEGER")
        cur.execute("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS file_name TEXT")
        cur.execute("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS version INTEGER")

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
