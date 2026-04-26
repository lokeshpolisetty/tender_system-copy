# 🏛️ Government Tender & Contract Management System

A complete, production-ready **e-Procurement Portal** built with Python Flask, PostgreSQL, and Bootstrap 5.

---

## 📋 Table of Contents
1. [Features](#features)
2. [Architecture](#architecture)
3. [Quick Start (Local)](#quick-start-local)
4. [Environment Variables](#environment-variables)
5. [CLI Commands](#cli-commands)
6. [AWS Deployment](#aws-deployment)
7. [API Reference](#api-reference)
8. [Security Notes](#security-notes)
9. [Project Structure](#project-structure)

---

## ✨ Features

| Feature | Details |
|---|---|
| **Role-based Auth** | Admin, Vendor, Auditor with RBAC decorators |
| **Email Verification** | Signed token via itsdangerous |
| **Password Reset** | Time-limited secure tokens |
| **Digital Signature** | Mock upload & verification |
| **Tender Management** | Create, publish, edit, cancel with full lifecycle |
| **Bid Encryption** | AES-128-CBC via Fernet — bids sealed until opening |
| **Document Processing** | PDF (pdfminer/PyPDF2) + DOCX auto-extraction |
| **Bid Ranking** | Automatic L1 (lowest bidder) ranking on opening |
| **Fraud Detection** | Cartelization, repeated winners, abnormal bids |
| **Audit Trail** | SHA-256 hash-chained immutable log |
| **Analytics Dashboard** | Chart.js charts, category/monthly trends |
| **Email Notifications** | SMTP alerts for all key events |
| **REST API** | JWT-protected API endpoints |
| **Pagination** | All list views paginated |
| **Search & Filter** | Full-text search + multi-filter on tenders |
| **CSRF Protection** | Flask-WTF on all forms |

---

## 🏗️ Architecture

```
tender_system/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── models.py            # SQLAlchemy ORM models
│   ├── auth/                # Blueprint: register, login, profile
│   ├── tenders/             # Blueprint: CRUD, publish, open bids
│   ├── bids/                # Blueprint: submit, view, withdraw
│   ├── analytics/           # Blueprint: charts, audit log, fraud
│   ├── main/                # Blueprint: home, dashboard, notifications
│   ├── api/                 # Blueprint: JWT REST API
│   ├── utils/
│   │   ├── audit.py         # Hash-chained audit log writer
│   │   ├── bid_encryption.py# Fernet encrypt/decrypt bid amounts
│   │   ├── bid_processor.py # Reveal + rank bids after deadline
│   │   ├── decorators.py    # RBAC decorators (role_required)
│   │   ├── doc_processor.py # PDF/DOCX data extraction
│   │   ├── email.py         # Flask-Mail notification helpers
│   │   ├── file_handler.py  # Secure upload with path traversal guard
│   │   └── security.py      # itsdangerous token helpers
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS, JS, uploads
├── config.py                # Dev / Test / Production configs
├── run.py                   # Entry point + CLI commands
├── gunicorn.conf.py         # Production WSGI config
├── requirements.txt
└── .env.example
```

---

## 🚀 Quick Start (Local)

### 1. Prerequisites
- Python 3.10+
- PostgreSQL 14+
- (Optional) Redis for rate limiting

### 2. Clone & Set Up

```bash
# Navigate to project
cd tender_system

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Create PostgreSQL Database

```sql
-- Run in psql as superuser
CREATE DATABASE tender_dev;
CREATE USER tender_user WITH PASSWORD 'StrongPassword123';
GRANT ALL PRIVILEGES ON DATABASE tender_dev TO tender_user;
```

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual values:
nano .env
```

**Minimum required values in `.env`:**
```bash
FLASK_ENV=development
SECRET_KEY=<random 32-byte hex>
JWT_SECRET_KEY=<another random secret>
DEV_DATABASE_URL=postgresql://tender_user:StrongPassword123@localhost:5432/tender_dev
BID_ENCRYPTION_KEY=<fernet key>
```

Generate keys:
```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# BID_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 5. Initialize Database & Create Admin

```bash
# Create tables
flask --app run init-db

# OR using Flask-Migrate
flask --app run db init
flask --app run db migrate -m "Initial schema"
flask --app run db upgrade

# Create the first admin account
flask --app run create-admin
# Enter name, email, password when prompted
```

### 6. Run Development Server

```bash
python run.py
# Server starts at http://localhost:5000
```

### 7. Test Accounts

After running `flask create-admin`, register vendor and auditor accounts via the UI at `/auth/register`.

> **Note:** Email verification links are printed to the console in development if SMTP is not configured. Check your terminal for the verify URL.

---

## 🔧 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | Flask secret key for sessions & CSRF |
| `JWT_SECRET_KEY` | ✅ | JWT signing key |
| `DEV_DATABASE_URL` | ✅ (dev) | PostgreSQL connection string |
| `DATABASE_URL` | ✅ (prod) | PostgreSQL connection (production) |
| `BID_ENCRYPTION_KEY` | ✅ | Fernet key for bid encryption |
| `MAIL_SERVER` | Recommended | SMTP host (e.g. smtp.gmail.com) |
| `MAIL_USERNAME` | Recommended | SMTP username |
| `MAIL_PASSWORD` | Recommended | SMTP app password |
| `USE_S3` | Optional | `true` to use AWS S3 for file storage |
| `AWS_ACCESS_KEY_ID` | If S3 | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | If S3 | AWS secret key |
| `AWS_S3_BUCKET` | If S3 | S3 bucket name |
| `REDIS_URL` | Optional | Redis for rate limiting |

---

## 🖥️ CLI Commands

```bash
# Create all database tables
flask --app run init-db

# Bootstrap first admin user (interactive)
flask --app run create-admin

# Open Flask REPL with all models pre-loaded
flask --app run shell

# Database migrations (Flask-Migrate)
flask --app run db migrate -m "Description"
flask --app run db upgrade
flask --app run db downgrade
```

---

## ☁️ AWS Deployment

### Architecture

```
Internet → ALB (HTTPS) → EC2 Auto Scaling Group
                              ↓
                    Gunicorn (Flask App)
                         ↓         ↓
                    RDS Postgres  S3 Bucket
                    (ap-south-1)  (file uploads)
```

### Step 1: Launch EC2 Instance

```bash
# Recommended: Ubuntu 22.04 LTS, t3.medium or larger
# Security Group: allow ports 22 (SSH), 80 (HTTP), 443 (HTTPS)
```

### Step 2: Install Dependencies on EC2

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx postgresql-client git

# Clone project
git clone https://github.com/your-org/tender-system.git /opt/tender_system
cd /opt/tender_system

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Create AWS RDS PostgreSQL

```bash
# Via AWS Console or CLI:
aws rds create-db-instance \
    --db-instance-identifier tender-prod \
    --db-instance-class db.t3.medium \
    --engine postgres \
    --master-username tender_admin \
    --master-user-password "YourStrongPassword" \
    --allocated-storage 20 \
    --db-name tender_prod \
    --region ap-south-1 \
    --no-publicly-accessible
```

### Step 4: Create S3 Bucket (for file uploads)

```bash
aws s3 mb s3://tender-uploads-prod --region ap-south-1

# Bucket policy — block public access
aws s3api put-public-access-block \
    --bucket tender-uploads-prod \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### Step 5: Configure Production Environment

```bash
# /opt/tender_system/.env
FLASK_ENV=production
SECRET_KEY=<strong-random-key>
JWT_SECRET_KEY=<another-strong-key>
DATABASE_URL=postgresql://tender_admin:YourStrongPassword@tender-prod.xxxx.ap-south-1.rds.amazonaws.com:5432/tender_prod
BID_ENCRYPTION_KEY=<fernet-key>
USE_S3=true
AWS_S3_BUCKET=tender-uploads-prod
AWS_S3_REGION=ap-south-1
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your@gmail.com
MAIL_PASSWORD=app-password
```

### Step 6: Initialize DB & Create Admin

```bash
cd /opt/tender_system
source venv/bin/activate
flask --app run init-db
flask --app run create-admin
```

### Step 7: Create Systemd Service

```bash
sudo nano /etc/systemd/system/tender.service
```

```ini
[Unit]
Description=Gov Tender Portal (Gunicorn)
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/tender_system
EnvironmentFile=/opt/tender_system/.env
ExecStart=/opt/tender_system/venv/bin/gunicorn -c gunicorn.conf.py "run:app"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tender
sudo systemctl start tender
sudo systemctl status tender
```

### Step 8: Configure Nginx as Reverse Proxy

```bash
sudo nano /etc/nginx/sites-available/tender
```

```nginx
server {
    listen 80;
    server_name your-domain.gov.in;

    # Redirect HTTP → HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.gov.in;

    ssl_certificate     /etc/ssl/certs/tender.crt;
    ssl_certificate_key /etc/ssl/private/tender.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 20M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias /opt/tender_system/app/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/tender /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 9: SSL Certificate (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.gov.in
```

### Step 10: Set Up Automated Backups (RDS)

```bash
# Enable automated backups in RDS (7-day retention recommended)
aws rds modify-db-instance \
    --db-instance-identifier tender-prod \
    --backup-retention-period 7 \
    --preferred-backup-window "02:00-03:00"
```

### Monitoring (CloudWatch)

```bash
# Install CloudWatch agent for EC2 metrics
sudo apt install -y amazon-cloudwatch-agent
# Configure via /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
```

---

## 🔌 API Reference

All API endpoints are at `/api/v1/`.

### Authentication

```bash
# Get tokens
POST /api/v1/auth/login
Content-Type: application/json
{"email": "admin@gov.in", "password": "password"}

# Response
{"access_token": "eyJ...", "refresh_token": "eyJ...", "user": {...}}

# Use token
GET /api/v1/tenders
Authorization: Bearer eyJ...
```

### Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/login` | None | Get JWT tokens |
| POST | `/api/v1/auth/refresh` | Refresh JWT | Refresh access token |
| GET | `/api/v1/tenders` | None | List published tenders |
| GET | `/api/v1/tenders/<id>` | None | Tender detail |
| GET | `/api/v1/bids` | Vendor JWT | My submitted bids |
| GET | `/api/v1/analytics/overview` | Admin/Auditor JWT | Stats overview |

---

## 🔐 Security Notes

1. **Bid Encryption:** Bids use Fernet (AES-128-CBC + HMAC-SHA256). The key is derived from `SECRET_KEY` if `BID_ENCRYPTION_KEY` is not set. In production, always set an explicit `BID_ENCRYPTION_KEY`.

2. **Audit Trail Integrity:** Each audit log entry contains a SHA-256 hash of itself chained to the previous entry. The Auditor dashboard checks this chain and warns if tampering is detected.

3. **File Upload Security:** All uploads are sanitized with `werkzeug.utils.secure_filename`, given UUID-based names, and validated by extension. Files are stored outside the web root.

4. **CSRF Protection:** All state-changing forms include a WTForms CSRF token. Exempt only the JWT API blueprint.

5. **Password Hashing:** bcrypt with 12 rounds (development: 4 rounds for speed).

6. **Rate Limiting:** Configure `REDIS_URL` and use Flask-Limiter for production deployments.

7. **Production Checklist:**
   - [ ] Set strong `SECRET_KEY` and `JWT_SECRET_KEY`
   - [ ] Set explicit `BID_ENCRYPTION_KEY`
   - [ ] Enable HTTPS / TLS termination
   - [ ] Set `SESSION_COOKIE_SECURE=True` (auto in production config)
   - [ ] Configure SMTP for email verification
   - [ ] Enable RDS automated backups
   - [ ] Set up CloudWatch alarms for errors

---

## 📊 Database Schema

```
users          → tenders (admin_id)
users          → bids (vendor_id)
tenders        → bids (tender_id)
tenders        → tender_documents (tender_id)
bids           → bid_documents (bid_id)
users          → audit_logs (user_id)
users          → notifications (user_id)
```

---

## 🧪 Running Tests

```bash
# Install test deps
pip install pytest pytest-flask

# Set test env
export FLASK_ENV=testing

# Run tests
pytest tests/ -v
```

---

## 📝 License

Government of India — Internal Use. All rights reserved.
