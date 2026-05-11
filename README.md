# ☁️ Cloud Based Automatic File Backup & Recovery System

A professional, full-stack **SaaS-style** cloud backup platform built with **Flask**, **SQLite**, and **Supabase Storage**. Supports hierarchical folder management, intelligent file versioning, Google OAuth, SHA-256 deduplication, and an AI-powered assistant — all wrapped in a modern dark-mode UI.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔐 **Authentication** | Username/password login + **Google OAuth 2.0** (Sign in with Google) |
| 📁 **Folder Management** | Create, rename, delete folders with full hierarchical (nested) structure |
| 🧭 **Breadcrumb Navigation** | Google Drive-style path navigation for deep folder trees |
| ☁️ **Cloud Storage** | Files uploaded directly to **Supabase Storage** with folder-aware paths |
| 🤖 **AI Assistant** | Floating sidebar chatbot powered by **Groq (LLaMA 3.1)** — context-aware of your storage stats |
| 🛡️ **Duplicate Prevention** | SHA-256 hashing prevents identical files from being re-uploaded |
| 🔢 **Version Control** | Same filename → new version auto-assigned and stored |
| ↩️ **Restore** | Restore any previous version with one click |
| 🗑️ **Delete** | Delete specific file versions or empty folders |
| 📊 **Analytics Dashboard** | Stats for total files, versions, and storage across all folders |
| 🖱️ **Drag & Drop Upload** | Interactive drop zone with real-time progress bar |
| 📂 **Folder Upload Target** | Select destination folder before uploading from the dashboard |
| 🛡️ **Admin Panel** | Admin-only dashboard for global system analytics |
| 📋 **Activity Logs** | Tracks all upload, download, restore, and delete actions |
| 📱 **Fully Responsive** | Bootstrap 5 — works on desktop, tablet, and mobile |

---

## 🚀 Quick Start

### 1. Clone / open the project

```bash
cd cloud_backup_project
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Supabase (https://supabase.com)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-or-service-role-key

# Flask session secret
SECRET_KEY=any-random-string-here

# Google OAuth 2.0 (https://console.cloud.google.com)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Groq AI (https://console.groq.com/keys)
GROQ_API_KEY=gsk_your-groq-api-key
```

### 5. Set up Supabase

1. Go to [supabase.com](https://supabase.com) → create a free project.
2. In **Storage** → create a bucket named **`files`**.
3. Set bucket to **Public** so download URLs work.
4. Copy your **Project URL** and **anon key** from Project Settings → API.

### 6. Set up Google OAuth (optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials.
2. Create an **OAuth 2.0 Client ID** (Web application).
3. Add **Authorized JavaScript origins**: `http://localhost:5000`
4. Add **Authorized redirect URIs**: `http://localhost:5000/auth/google`
5. Copy Client ID and Secret into `.env`.

### 7. Run the app

```bash
python app.py
```

Open your browser at **http://localhost:5000**

> ⚠️ Use `localhost:5000` (not `127.0.0.1:5000`) for Google OAuth to work correctly.

---

## 📁 Project Structure

```
cloud_backup_project/
├── app.py                  # Flask backend — routes, DB, Supabase, AI, OAuth
├── database.db             # SQLite database (auto-created on first run)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed to git)
├── .env.example            # Template for environment variables
├── uploads/                # Temporary upload folder (auto-cleared)
├── templates/
│   ├── base.html           # Shared layout (navbar, flash messages)
│   ├── login.html          # Login page with Google OAuth button
│   ├── register.html       # Registration page
│   ├── dashboard.html      # Stats, drag-and-drop upload, AI sidebar
│   ├── files.html          # File & folder manager with breadcrumbs
│   └── admin_dashboard.html# Admin-only analytics view
└── static/
    ├── css/
    └── js/
```

---

## 🗄️ Database Schema

```sql
-- users
CREATE TABLE users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT    NOT NULL UNIQUE,
    password  TEXT    NOT NULL,       -- SHA-256 hashed
    role      TEXT    DEFAULT 'user', -- 'user' or 'admin'
    google_id TEXT,                   -- Google OAuth sub ID
    email     TEXT
);

-- folders (hierarchical)
CREATE TABLE folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    parent_id  INTEGER REFERENCES folders(id), -- NULL = root
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL
);

-- files (one row per version)
CREATE TABLE files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT    NOT NULL,
    supabase_path TEXT    NOT NULL,   -- path inside Supabase bucket
    file_size     INTEGER DEFAULT 0,
    file_hash     TEXT,               -- SHA-256 for duplicate prevention
    version       INTEGER NOT NULL,
    timestamp     TEXT    NOT NULL,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    folder_id     INTEGER REFERENCES folders(id) -- NULL = root
);

-- activity logs
CREATE TABLE activity_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    action_type TEXT    NOT NULL,  -- 'upload', 'download', 'restore', 'delete'
    file_name   TEXT    NOT NULL,
    version     INTEGER,
    timestamp   TEXT    NOT NULL
);
```

---

## 🔑 API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/login` | Username/password login |
| GET | `/login/google` | Initiate Google OAuth login |
| GET | `/auth/google` | Google OAuth callback |
| GET/POST | `/register` | Register new account |
| GET | `/logout` | Log out |
| GET | `/dashboard` | Dashboard with stats & upload |
| GET | `/files` | File & folder manager (supports `?folder_id=`) |
| POST | `/upload` | Upload file via AJAX (supports `folder_id` form field) |
| GET | `/download/<id>` | Download a specific file version |
| GET/POST | `/restore/<id>` | Restore an older version as new |
| POST | `/delete/<id>` | Delete a specific file version |
| POST | `/create_folder` | Create a new folder |
| POST | `/rename_folder/<id>` | Rename an existing folder |
| POST | `/delete_folder/<id>` | Delete an empty folder |
| POST | `/chat` | Talk to the Groq AI Assistant |
| GET | `/admin` | Admin dashboard (admin role only) |

---

## 🎨 Design System

- **Theme**: Dark mode — deep navy/midnight blue
- **Color palette**: `#0d0d1a` bg · `#4e8fff` primary · `#00c48c` success · `#ff4d6d` danger
- **Font**: Inter (Google Fonts)
- **Framework**: Bootstrap 5.3 + Bootstrap Icons
- **Animations**: CSS slide-down, fade-in, hover lifts, floating AI toggle button

---

## 🤖 AI Assistant

The floating AI sidebar is powered by **Groq's LLaMA 3.1 8B Instant** model. It is context-aware of:

- Total files and versions stored
- Total storage consumed
- Number of folders created
- Recent activity (last 5 actions)

Get a free Groq API key at [console.groq.com/keys](https://console.groq.com/keys).

---

## 👤 Default Admin Account

On first run, an admin account is auto-created:

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin123` |

> ⚠️ Change the admin password after first login in a production environment.

---

## 📦 Dependencies

```
Flask==3.0.0
Werkzeug==3.0.1
supabase==2.30.0
python-dotenv==1.0.0
groq==1.2.0
Authlib
requests
websockets==15.0.1
```

---

## 📄 License

This project is built for educational purposes as part of a Cloud Computing course.
