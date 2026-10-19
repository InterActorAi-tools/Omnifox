# 🏺 Omnicat - Enterprise Comment Sentiment Analysis Platform

![Version](https://img.shields.io/badge/version-2.1.0-green.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00d4aa.svg)
![React](https://img.shields.io/badge/React-18.0+-61dafb.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-336791.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

> Transform social media comments into actionable insights with AI-powered sentiment analysis, translation, and categorization. Now with enterprise-grade security and user management.

## ✨ New in v2.1.0

### 🔐 Enterprise Security & Auth

- **Secure Login**: Argon2 password hashing and JWT session management.
- **Two-Factor Authentication (2FA)**: Google Authenticator/TOTP support with backup codes.
- **Invitation-Only Access**: Admins generate secure links; no public registration.
- **Role-Based Access Control (RBAC)**: Granular permissions (Admin, Dashboard User, Basic User).
- **Session Management**: View and remotely revoke active sessions from any device.
- **Refresh-token rotation with reuse detection**: replaying a rotated refresh token invalidates every session for that user.

### 🐘 Production Architecture

- **PostgreSQL Database**: Migrated from SQLite for high concurrency and reliability.
- **Dockerized Deployment**: Backend, frontend, and Postgres ship together via `docker-compose`.
- **Automated CI/CD**: GitLab pipeline builds container images and runs the test suite on every push.

---

## 🚀 Features

### 🎯 Dual Processing Modes

- **📁 File Upload**: Process Excel files containing comments.
- **🔗 URL Extraction**: Extract comments directly from social media URLs.
  - Supports Facebook, YouTube, Instagram, Twitter/X, TikTok.
  - **Reply Flattening**: Automatically extracts and analyzes nested replies.

### 🤖 AI-Powered Analysis

- **Context-Aware Analysis**: Provide "Post Context" to help the AI understand sarcasm/relevance.
- **Sentiment Analysis**: Positive, Neutral, Negative classification.
- **Translation**: Auto-translate comments from any language to English.
- **Categorization**: Classify comments by topic (Politics, Security, Health, etc.).
- **Context Generation**: AI-generated summaries for each sentiment category.

### 📊 Enhanced Analytics Dashboard

- **User Activity Logs**: Track who did what and when.
- **Project Breakdown**: Track usage by project for billing.
- **Date Filtering**: Filter analytics by custom date ranges.
- **Export Reports**: Download analytics data as CSV or JSON.
- **Real-time Updates**: Live progress tracking for all operations.

---

## 🛠️ Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ (or Docker)

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd omnicat
```

### 2. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ../.env.example ../.env
# Edit ../.env (see "Configuration" section below).
#
# For first-time setup, set FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD in
# .env. The backend will create the admin user on first boot when the
# users table is empty. After it succeeds, REMOVE those two values from
# .env and restart - they are only needed once.

# Start the server (roles, permissions, and first admin seed automatically on boot)
python main.py
```

Alternative: seed manually instead of using `FIRST_ADMIN_*` env vars.

```bash
python -m cli init                            # idempotent: roles + permissions
python -m cli create-admin                    # interactive: prompts for email + password
python -m cli promote-admin user@example.com  # grant admin to an existing user
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev    # or `npm run build` for a production bundle
```

---

## 🚢 Server Deployment

Production and staging are deployed via `docker-compose`. The compose file (`docker-compose.yml`) defines a backend container, a frontend container, and a Postgres database container on a private Docker network. TLS termination is expected to happen on the host reverse proxy in front of the stack.

### 1. Configure secrets

```bash
cp .env.example .env
# Edit .env on the target server and fill in real values.
# Never commit a real .env to git.
```

### 2. Bring the stack up

```bash
docker compose pull
docker compose up -d
```

The backend container will run database migrations, seed roles and permissions, and (if `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` are set) create the initial admin on first boot. Remove those two values from `.env` after the first successful start.

---

## 🔧 Configuration (`.env`)

Reference: see [`.env.example`](.env.example) for the full, commented template. Key variables:

```ini
# ---- Runtime ----
ENVIRONMENT=production
DEBUG=False
CORS_ORIGINS=https://omnicat.example.com

# ---- Database ----
POSTGRES_USER=omnicat
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=omnicat
DATABASE_URL=postgresql+psycopg2://omnicat:<password>@db:5432/omnicat

# ---- Backend secrets ----
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
# The app refuses to start if this is unset.
JWT_SECRET_KEY=<your-jwt-secret>

GEMINI_API_KEY=<your-gemini-api-key>
EXPORTCOMMENTS_API_KEY=<your-exportcomments-api-key>
RESEND_API_KEY=<your-resend-api-key>

GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<your-google-oauth-client-secret>

# ---- First-boot admin (remove after first successful start) ----
FIRST_ADMIN_EMAIL=
FIRST_ADMIN_PASSWORD=
FIRST_ADMIN_NAME=Super Admin

# ---- Backend tuning ----
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=120
```

---

## 📋 API Endpoints

### Authentication

- `POST /api/auth/login` - Login with email/password
- `POST /api/auth/verify-2fa` - Verify TOTP code or backup code
- `POST /api/auth/refresh` - Rotate refresh token + issue new access token
- `POST /api/auth/logout` - Revoke the current session

### Processing

- `POST /api/upload/process/{client_id}` - Process an uploaded Excel file
- `POST /api/process_url/{client_id}` - Extract and process comments from a URL
- `GET  /api/progress/{client_id}` - Server-sent events progress stream (auth required via `?token=<jwt>`)

### Admin

- `POST   /api/admin/invitations/generate` - Generate an invite link
- `GET    /api/admin/users` - List all users
- `DELETE /api/admin/users/{id}/sessions/{session_id}` - Revoke a specific user session

---

## 🏗️ Architecture

```text
omnicat/
├── 🐍 Backend (FastAPI + PostgreSQL)
│   ├── main.py                # App entry point
│   ├── config.py              # Settings management
│   ├── models/                # SQLAlchemy database models
│   │   ├── user.py            # User & auth models
│   │   ├── invitation.py      # Invite system
│   │   └── ...
│   ├── routers/               # API routes (auth, admin, users)
│   ├── api/routes/            # Upload + extraction routes
│   ├── services/              # Business logic (Gemini, ExportComments, processing)
│   ├── utils/                 # Security helpers (paths, url_safety, security)
│   └── tests/                 # Pytest suite
│
├── ⚛️ Frontend (React + Vite + Tailwind)
│   ├── src/components/        # UI components
│   ├── src/pages/             # Page layouts
│   └── src/services/          # API client (Axios)
│
├── 🐳 Deployment
│   ├── docker-compose.yml     # Backend + frontend + Postgres stack
│   └── .env.example           # Configuration template
│
└── 📚 Docs
    └── docs/SECURITY_ASSESSMENT.md   # Security findings + remediation status
```

---

## 🔒 Security

A full security assessment with remediation status lives in [`docs/SECURITY_ASSESSMENT.md`](docs/SECURITY_ASSESSMENT.md). Highlights of what has shipped:

- JWT secret is required at startup (no insecure default).
- Path-traversal defense on every upload/download/list/delete/process endpoint.
- SSE progress stream is authenticated and scoped to the token's user.
- Refresh-token rotation with reuse detection: replaying a rotated token wipes every session for that user.
- SSRF defense on the ExportComments download fetch: scheme + hostname allowlist, public-IP-only DNS, connection pinning to defeat DNS rebinding, no redirects.

Outstanding items (rate limiting, CSP/security headers, prompt-injection hardening, history purge of historically leaked secrets) are tracked in the assessment document.

---

## 📄 License

MIT.
