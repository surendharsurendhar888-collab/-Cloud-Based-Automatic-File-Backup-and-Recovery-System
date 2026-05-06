# Cloud Based Automatic File Backup & Recovery System

A full-stack web application built with **Flask**, **SQLite**, and **Supabase Storage** that lets users securely upload, version, download, and restore files from the cloud. It now features an intelligent **Cloud AI Assistant** powered by Google Gemini.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔐 Authentication | Register / login with hashed passwords (Werkzeug) |
| ☁️ Cloud Storage | Files uploaded directly to Supabase Storage |
| 🤖 AI Assistant | Floating ChatGPT-style sidebar powered by `gemini-2.5-flash-lite` |
| 🛡️ Duplicate Prevention | SHA-256 hashing to ensure identical files aren't uploaded multiple times |
| 🔢 Version Control | Same filename → new version number auto-assigned |
| ↩️ Restore | Restore any previous version with one click |
| 📊 Analytics | Stats cards tracking total files and total versions |
| 🖱️ Drag & Drop | Interactive drop zone with upload progress bar |
| 📱 Responsive | Bootstrap 5 – mobile friendly |

---

## 🚀 Quick Start

### 1. Clone / open the project in VS Code

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

### 4. Set up Supabase & Gemini API

1. Go to [supabase.com](https://supabase.com) → create a free project.
2. In Storage → create a bucket named **`files`** (set it to **Public** so download URLs work).
3. Copy your **Project URL** and **anon/service key** from Project Settings → API.
4. Get a free API key from [Google AI Studio](https://aistudio.google.com/) for the Gemini AI chatbot.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-or-service-role-key
SECRET_KEY=any-random-string-here
GEMINI_API_KEY=your-gemini-api-key
```

### 6. Run the app

```bash
python app.py
```

Open your browser at **http://localhost:5000**

---

## 📁 Project Structure

```
cloud_backup_project/
├── app.py                # Flask backend (routes, DB, Supabase, AI logic)
├── database.db           # SQLite database (auto-created)
├── requirements.txt
├── .env.example          # Template for environment variables
├── uploads/              # Temporary local folder (auto-cleared)
├── templates/
│   ├── base.html         # Shared layout (navbar, flash messages)
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html    # Stats, drag-and-drop upload, floating AI sidebar
│   └── files.html        # File manager with version history
└── static/
    ├── css/
    │   ├── style.css
    │   └── dashboard.css # Scoped styles for the AI Assistant
    └── js/
        ├── main.js
        └── dashboard_chat.js # Logic for the AI Assistant Sidebar
```

---

## 🗄️ Database Schema

```sql
-- users
CREATE TABLE users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL          -- bcrypt hash via Werkzeug
);

-- files (one row per version)
CREATE TABLE files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    supabase_path TEXT NOT NULL,    -- path inside Supabase bucket
    file_size     INTEGER DEFAULT 0,
    file_hash     TEXT,             -- SHA-256 for duplicate prevention
    version       INTEGER NOT NULL,
    timestamp     TEXT NOT NULL,    -- UTC YYYYMMDD_HHMMSS
    user_id       INTEGER NOT NULL REFERENCES users(id)
);
```

---

## 🔑 API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/login` | Login page |
| GET/POST | `/register` | Register page |
| GET | `/logout` | Log out |
| GET | `/dashboard` | Dashboard + stats |
| GET | `/files` | File manager |
| GET | `/files/versions/<name>` | JSON version list |
| POST | `/upload` | Upload file (AJAX) |
| GET | `/download/<id>` | Download specific version |
| GET | `/restore/<id>` | Restore old version |
| POST | `/delete/<id>` | Delete a version |
| POST | `/chat` | Talk to the Gemini Cloud AI Assistant |

---

## 🎨 Design

- **Color palette**: Deep navy (#0d1b2a) + Blue (#3b82f6) + Green accent (#22c55e)
- **Font**: Inter (Google Fonts)
- **Framework**: Bootstrap 5.3
- **Animations**: CSS slide-up, fade-in, hover lifts, floating AI toggle.
