"""
Application entry point.

Development:  python run.py
Production:   gunicorn -c gunicorn.conf.py "run:app"
"""

import os
from app import create_app, db
from app.models import (User, Tender, Bid, BidDocument, TenderDocument,
                        AuditLog, Notification, UserRole)

app = create_app(os.environ.get('FLASK_ENV', 'development'))


# ── Health check endpoint (required by ALB target group) ─────────────────────
# This must be on the app object, NOT inside a blueprint, so it's always
# available even if blueprints fail to load partially.
@app.route('/health')
def health_check():
    """ALB health check — returns 200 with no auth required."""
    from flask import jsonify
    try:
        # Quick DB connectivity check
        db.session.execute(db.text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return jsonify({'status': 'ok' if db_ok else 'degraded', 'db': db_ok}), status


# ── Shell context ─────────────────────────────────────────────────────────────
@app.shell_context_processor
def make_shell_context():
    """Inject models into `flask shell` for convenient REPL access."""
    return {
        'db': db,
        'User': User,
        'Tender': Tender,
        'Bid': Bid,
        'BidDocument': BidDocument,
        'TenderDocument': TenderDocument,
        'AuditLog': AuditLog,
        'Notification': Notification,
        'UserRole': UserRole,
    }


# ── CLI commands ──────────────────────────────────────────────────────────────

@app.cli.command('create-admin')
def create_admin():
    """
    Bootstrap the first admin account — INTERACTIVE mode.

    Usage:
        flask --app run create-admin
    """
    import getpass

    print('\n=== Create Admin Account ===')
    name  = input('Full name: ').strip()
    email = input('Email: ').strip().lower()
    pwd   = getpass.getpass('Password: ')

    if User.query.filter_by(email=email).first():
        print(f'ERROR: {email} is already registered.')
        return

    admin = User(
        name=name,
        email=email,
        role=UserRole.ADMIN,
        organization='Government of India',
        is_active=True,
        email_verified=True,
    )
    admin.set_password(pwd)
    db.session.add(admin)
    db.session.commit()
    print(f'\n✓ Admin account created: {email}')


@app.cli.command('create-admin-noninteractive')
def create_admin_noninteractive():
    """
    Bootstrap the first admin account from environment variables.
    Used by EC2 User Data and CI/CD pipelines where stdin is not available.

    Required environment variables:
        ADMIN_NAME     e.g. "Portal Administrator"
        ADMIN_EMAIL    e.g. "admin@tender.gov.in"
        ADMIN_PASSWORD e.g. fetched from Secrets Manager

    Usage:
        ADMIN_NAME="..." ADMIN_EMAIL="..." ADMIN_PASSWORD="..." \\
            flask --app run create-admin-noninteractive
    """
    name  = os.environ.get('ADMIN_NAME', 'Portal Administrator')
    email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    pwd   = os.environ.get('ADMIN_PASSWORD', '').strip()

    if not email:
        print('ERROR: ADMIN_EMAIL environment variable is not set.')
        return
    if not pwd:
        print('ERROR: ADMIN_PASSWORD environment variable is not set.')
        return
    if len(pwd) < 12:
        print('ERROR: ADMIN_PASSWORD must be at least 12 characters.')
        return

    if User.query.filter_by(email=email).first():
        print(f'Admin {email} already exists — skipping.')
        return

    admin = User(
        name=name,
        email=email,
        role=UserRole.ADMIN,
        organization='Government of India',
        is_active=True,
        email_verified=True,
    )
    admin.set_password(pwd)
    db.session.add(admin)
    db.session.commit()
    print(f'✓ Admin account created: {email}')


@app.cli.command('init-db')
def init_db():
    """Create all database tables (bypasses Alembic — use for first launch)."""
    db.create_all()
    print('✓ Database tables created.')


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=(os.environ.get('FLASK_ENV', 'development') == 'development'),
    )
