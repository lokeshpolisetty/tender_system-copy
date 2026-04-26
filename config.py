"""
Configuration module for Government Tender & Contract Management System.
Upgraded for full AWS deployment with Cognito, SES, SNS, Textract, S3, RDS.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""

    # ── Core ──────────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # ── Database (Amazon RDS PostgreSQL) ──────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
    }

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-change-in-production'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # ── File Uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'}

    # ── Amazon S3 ─────────────────────────────────────────────────────────────
    USE_S3 = os.environ.get('USE_S3', 'false').lower() == 'true'
    AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET')
    AWS_S3_REGION = os.environ.get('AWS_S3_REGION', 'ap-south-1')
    # Do NOT set AWS_ACCESS_KEY_ID / SECRET in prod — use IAM Instance Role instead

    # ── Amazon SES ────────────────────────────────────────────────────────────
    USE_SES = os.environ.get('USE_SES', 'false').lower() == 'true'
    AWS_SES_REGION = os.environ.get('AWS_SES_REGION', 'ap-south-1')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@tender.gov.in')
    # Flask-Mail fallback (local dev only)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # ── Amazon SNS ────────────────────────────────────────────────────────────
    AWS_SNS_REGION = os.environ.get('AWS_SNS_REGION', 'ap-south-1')
    SNS_TENDER_PUBLISHED_TOPIC_ARN = os.environ.get('SNS_TENDER_PUBLISHED_TOPIC_ARN')
    SNS_BID_AWARDED_TOPIC_ARN = os.environ.get('SNS_BID_AWARDED_TOPIC_ARN')

    # ── Amazon Textract ───────────────────────────────────────────────────────
    USE_TEXTRACT = os.environ.get('USE_TEXTRACT', 'false').lower() == 'true'

    # ── Amazon Cognito ────────────────────────────────────────────────────────
    USE_COGNITO = os.environ.get('USE_COGNITO', 'false').lower() == 'true'
    COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID')
    COGNITO_APP_CLIENT_ID = os.environ.get('COGNITO_APP_CLIENT_ID')
    COGNITO_REGION = os.environ.get('COGNITO_REGION', 'ap-south-1')
    COGNITO_DOMAIN = os.environ.get('COGNITO_DOMAIN')  # e.g. tender-portal.auth.ap-south-1.amazoncognito.com

    # ── Amazon API Gateway ────────────────────────────────────────────────────
    # Set BEHIND_API_GATEWAY=true when the app sits behind API Gateway HTTP API
    BEHIND_API_GATEWAY = os.environ.get('BEHIND_API_GATEWAY', 'false').lower() == 'true'

    # ── Bid Encryption ────────────────────────────────────────────────────────
    BID_ENCRYPTION_KEY = os.environ.get('BID_ENCRYPTION_KEY')

    # ── Pagination ────────────────────────────────────────────────────────────
    TENDERS_PER_PAGE = 10
    BIDS_PER_PAGE = 20
    LOGS_PER_PAGE = 50

    # ── Security ──────────────────────────────────────────────────────────────
    BCRYPT_LOG_ROUNDS = 12
    TOKEN_EXPIRY_HOURS = 24

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'memory://')

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.path.join(BASE_DIR, 'logs', 'app.log')


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        'postgresql://postgres:password@localhost:5432/tender_dev'
    SQLALCHEMY_ECHO = False
    BCRYPT_LOG_ROUNDS = 4


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or 'sqlite:///:memory:'
    BCRYPT_LOG_ROUNDS = 4
    MAIL_SUPPRESS_SEND = True
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    BCRYPT_LOG_ROUNDS = 13

    # Force HTTPS
    PREFERRED_URL_SCHEME = 'https'
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    # AWS services ON in production
    USE_S3 = True
    USE_SES = True
    USE_TEXTRACT = True

    SEND_FILE_MAX_AGE_DEFAULT = 31536000


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
