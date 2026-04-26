"""Audit trail utility — write tamper-evident log entries."""

from datetime import datetime, timezone
from typing import Optional

from flask import current_app, request

from app import db
from app.models import AuditAction, AuditLog


def log_action(
    action: AuditAction,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    description: str = '',
    ip_address: Optional[str] = None,
    extra_data: Optional[dict] = None,
) -> Optional[AuditLog]:
    """
    Create an immutable audit log entry with a SHA-256 hash chain.

    Parameters
    ----------
    action       : One of the AuditAction enum values.
    user_id      : ID of the acting user (None for system actions).
    resource_type: Affected entity type ('tender', 'bid', 'user').
    resource_id  : Affected entity ID.
    description  : Human-readable description.
    ip_address   : Client IP (auto-detected from request if not supplied).
    extra_data   : Additional context dict stored as JSON.
    """
    import json

    try:
        ip = ip_address
        ua = None
        if request:
            try:
                ip = ip or request.remote_addr
                ua = request.user_agent.string[:500] if request.user_agent else None
            except RuntimeError:
                pass  # Outside of request context

        entry = AuditLog(
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            ip_address=ip,
            user_agent=ua,
            extra_data=json.dumps(extra_data) if extra_data else None,
            timestamp=datetime.now(timezone.utc),
        )
        entry.set_hash()

        db.session.add(entry)
        db.session.commit()
        return entry

    except Exception as exc:
        current_app.logger.error(f'Audit log write failed: {exc}')
        db.session.rollback()
        return None
