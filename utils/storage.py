import os
from supabase import create_client, Client
from dotenv import dotenv_values

# ─── Environment Setup ────────────────────────────────────────────────────────
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(UTILS_DIR)
env_config = dotenv_values(os.path.join(PROJECT_DIR, ".env"))

SUPABASE_URL = env_config.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_KEY = env_config.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
BUCKET_NAME  = "files"

# Create Supabase client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[ERROR] Failed to initialize Supabase client: {e}")

def get_folder_path_list(folder_id, conn):
    """Returns a list of dicts [{'id': 1, 'name': 'Folder1'}, ...] for breadcrumbs."""
    import psycopg2.extras
    path = []
    current_id = folder_id
    while current_id:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, name, parent_id FROM folders WHERE id = %s", (current_id,))
            row = cur.fetchone()
        if not row:
            break
        path.insert(0, {"id": row["id"], "name": row["name"]})
        current_id = row["parent_id"]
    return path

def get_supabase_folder_path(folder_id, conn):
    """Returns a string path like 'Folder1/Folder2' or empty string."""
    from werkzeug.utils import secure_filename
    if not folder_id:
        return ""
    path_list = get_folder_path_list(folder_id, conn)
    return "/".join([secure_filename(f["name"]) for f in path_list])
