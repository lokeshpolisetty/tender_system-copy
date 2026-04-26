"""Role-based access control decorators."""

from functools import wraps

from flask import abort, jsonify
from flask_jwt_extended import get_jwt
from flask_login import current_user

from app.models import UserRole


def role_required(*roles):
    """
    Flask-Login decorator: allow only users with one of the specified roles.

    Usage::

        @role_required(UserRole.ADMIN)
        @role_required(UserRole.ADMIN, UserRole.AUDITOR)
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_role(*roles):
                abort(403)
            if current_user.is_suspended:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def api_role_required(*role_values: str):
    """
    JWT decorator: allow only tokens with one of the specified role strings.

    Usage::

        @jwt_required()
        @api_role_required('admin', 'auditor')
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            claims = get_jwt()
            user_role = claims.get('role', '')
            if user_role not in role_values:
                return jsonify({'error': 'Insufficient permissions.'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
