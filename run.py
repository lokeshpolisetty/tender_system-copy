"""
Application entry point.

Development:  python run.py
Production:   gunicorn "run:create_app('production')" -w 4 -b 0.0.0.0:8000
"""

import os
from app import create_app, db
from app.models import (User, Tender, Bid, BidDocument, TenderDocument,
                        AuditLog, Notification, UserRole)
from flask import current_app

app = create_app(os.environ.get('FLASK_ENV', 'development'))


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


@app.cli.command('create-admin')
def create_admin():
    """
    CLI command to bootstrap the first admin account.

    Usage:
        flask create-admin
    """
    import getpass
    from app.models import UserRole

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


@app.cli.command('init-db')
def init_db():
    """Create all database tables."""
    db.create_all()
    print('✓ Database tables created.')


@app.cli.command('seed-categories')
def seed_categories():
    """Optional: add sample tender categories for testing."""
    print('No seed data required — all data is created through the UI.')


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=(os.environ.get('FLASK_ENV', 'development') == 'development'),
    )
