# CloudProtect AI 🛡️💻
> **Production-Grade, AI-Powered SaaS File Backup, Tamper Verification, & Forensic Recovery System.**

CloudProtect AI is a state-of-the-art hybrid file synchronization, backup, and tamper-audit platform. Built on top of **Flask**, **PostgreSQL (Supabase DB)**, and **Supabase Blob Storage**, the platform is enhanced by **Groq LLaMA 3.1 AI** storage-behavior analytics, presenting a premium, glassmorphic UI.

---

## 🌟 Core Architecture & Features

### 1. High-Performance Deduplication Storage
*   **SHA-256 Hash Matching:** Every file uploaded is dynamically scanned and hashed. If the file bytes already exist on Supabase, the backend registers a reference instead of re-uploading, saving substantial bandwidth and storage resources.
*   **Version History Engine:** Automatic incremental versioning handles filename collisions by storing nested versions for audit recovery.

### 2. Microservice Decoupled Structure
*   **Modular Architecture (`utils/`):** Deconstructed from a monolithic design into focused helper micro-modules:
    *   [`utils/db.py`](file:///d:/project/cloud_backup_project/utils/db.py): Thread-safe `SimpleConnectionPool` lifecycle and migration schemas.
    *   [`utils/auth.py`](file:///d:/project/cloud_backup_project/utils/auth.py): Cryptographic password hashing and Flask session authenticators.
    *   [`utils/storage.py`](file:///d:/project/cloud_backup_project/utils/storage.py): Supabase API initialization and path calculation helpers.
    *   [`utils/ai.py`](file:///d:/project/cloud_backup_project/utils/ai.py): Groq Cloud AI LLaMA response wrappers.
    *   [`utils/helpers.py`](file:///d:/project/cloud_backup_project/utils/helpers.py): Configuration parser wrappers.

### 3. Smart Cybersecurity & Forensic Auditing
*   **Tamper Monitoring:** Audit trails track file actions (upload, download, restore, delete, star, profile update).
*   **Contextual AI Insights:** Floating assistant companion dynamically parses user storage behaviors and answers specific audit log queries using Groq's low-latency intelligence.

### 4. High-End Responsive User Experience
*   **Premium CSS Design:** Stunning neon-glassmorphic typography, smooth micro-interactions, responsive grids, and clean templates (segregated into logical `auth/`, `dashboard/`, `files/`, and `settings/` directories).
*   **Unified Fallbacks:** Optimized asset resolutions ensure clean profiles and loading fallbacks under any condition.

---

## 🛠️ Tech Stack & Dependencies

*   **Backend:** Python 3.10+, Flask
*   **Database:** PostgreSQL (with `psycopg2` connection pooling)
*   **Storage Cloud:** Supabase Storage Python SDK
*   **AI Integration:** Groq (Llama-3.1-8b-instant model)
*   **Frontend UI:** Vanilla CSS, Bootstrap 5 Icons & Core Grid
*   **Deployment:** Fully compatible with **Render** web service architecture

---

## 🚀 Local Quickstart Guide

### 1. Prerequisites
Install [Python 3.10+](https://python.org) on your computer.

### 2. Configure Environment Keys
Create a `.env` file in the project root:
```env
FLASK_SECRET_KEY="YOUR_SUPER_SECRET_SESSION_KEY"
DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@db.supabase.co:5432/postgres"
SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
SUPABASE_KEY="YOUR_SUPABASE_SERVICE_ROLE_KEY"
GROQ_API_KEY="gsk_YOUR_GROQ_KEY"

# Optional: Google OAuth Configuration
GOOGLE_CLIENT_ID="YOUR_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET="YOUR_GOOGLE_CLIENT_SECRET"
```

### 3. Install Packages
```bash
pip install -r requirements.txt
```

### 4. Seed Database tables
Execute the DDL schema dump on your PostgreSQL client:
```bash
psql -d "YOUR_DATABASE_URL" -f database/schema.sql
```
*(Note: App also auto-seeds standard tables and a default admin account username `admin` with password `admin123` on startup).*

### 5. Launch Development Server
```bash
python app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser!

---

## 📦 Production Deployment (Render / Heroku)

This repository is optimized for one-click web service deployments:
1. Set up a Web Service on Render.
2. Choose **Python** as the environment.
3. Configure the start command:
   ```bash
   gunicorn app:app
   ```
4. Add your `.env` variables under **Environment Variables** in Render's dashboard.
5. Deploy!

---

## 🛡️ License
Distributed under the MIT License. Created by surendharsurendhar888-collab.
