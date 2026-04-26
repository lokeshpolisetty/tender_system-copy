"""Security helpers: token generation, verification."""

from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import current_app


def generate_token(data: str, salt: str) -> str:
    """Generate a signed, time-limited token."""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(data, salt=salt)


def verify_token(token: str, salt: str, max_age: int = 86400):
    """
    Verify a token. Returns the original data string or None if invalid.
    max_age in seconds (default 24h).
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt=salt, max_age=max_age)
        return data
    except (SignatureExpired, BadSignature):
        return None
