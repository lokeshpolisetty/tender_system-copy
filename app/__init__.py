"""
Application factory for Government Tender & Contract Management System.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

# ── Extension instances (initialised in create_app) ──────────────────────────
db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
mail = Mail()
migrate = Migrate()
jwt = JWTManager()
csrf = CSRFProtect()


def create_app(config_name: str = None) -> Flask:
    """Application factory."""
    from config import config

    app = Flask(__name__, template_folder='templates', static_folder='static')

    # Load configuration
    cfg_name = config_name or os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config.get(cfg_name, config['default']))

    # ── Ensure upload directory exists ────────────────────────────────────────
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'tenders'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'bids'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'signatures'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(app.config.get('LOG_FILE', 'logs/app.log'))), exist_ok=True)

    # ── Initialise extensions ─────────────────────────────────────────────────
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    csrf.init_app(app)

    # ── Flask-Login settings ──────────────────────────────────────────────────
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # ── Register blueprints ───────────────────────────────────────────────────
    from app.auth.routes import auth_bp
    from app.tenders.routes import tenders_bp
    from app.bids.routes import bids_bp
    from app.analytics.routes import analytics_bp
    from app.main.routes import main_bp
    from app.api.routes import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(tenders_bp, url_prefix='/tenders')
    app.register_blueprint(bids_bp, url_prefix='/bids')
    app.register_blueprint(analytics_bp, url_prefix='/analytics')
    app.register_blueprint(api_bp, url_prefix='/api/v1')

    # ── Template context processors ───────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.models import Notification
        unread_count = 0
        if current_user.is_authenticated:
            unread_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False).count()
        return dict(unread_notification_count=unread_count)

    # ── Error handlers ────────────────────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        from flask import render_template
        return render_template('errors/500.html'), 500

    # ── Logging ───────────────────────────────────────────────────────────────
    _configure_logging(app)

    return app


def _configure_logging(app: Flask):
    """Set up rotating file handler + console handler."""
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'), logging.INFO)
    log_file = app.config.get('LOG_FILE', 'logs/app.log')

    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s (%(filename)s:%(lineno)d): %(message)s'
    )

    # File handler
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=10_485_760, backupCount=10)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        app.logger.addHandler(file_handler)
    except OSError:
        pass  # Non-fatal if log dir can't be created

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(log_level)
    app.logger.info('Tender Management System startup')
