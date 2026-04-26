"""Main routes: home, dashboard (role-aware), notifications."""

from datetime import datetime, timezone

from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user, login_required

from app import db
from app.models import (Bid, BidStatus, Notification, Tender, TenderStatus,
                        User, UserRole)

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Public landing page with latest published tenders."""
    recent_tenders = (Tender.query
                      .filter_by(status=TenderStatus.PUBLISHED)
                      .order_by(Tender.published_at.desc())
                      .limit(6).all())

    stats = {
        'total_tenders': Tender.query.filter(
            Tender.status != TenderStatus.DRAFT).count(),
        'active_tenders': Tender.query.filter_by(
            status=TenderStatus.PUBLISHED).count(),
        'awarded_tenders': Tender.query.filter_by(
            status=TenderStatus.AWARDED).count(),
        'registered_vendors': User.query.filter_by(
            role=UserRole.VENDOR, is_active=True).count(),
    }

    return render_template('main/index.html',
                           recent_tenders=recent_tenders,
                           stats=stats)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Role-aware dashboard redirect."""
    if current_user.is_admin:
        return _admin_dashboard()
    elif current_user.is_vendor:
        return _vendor_dashboard()
    elif current_user.is_auditor:
        return _auditor_dashboard()
    return render_template('main/index.html')


def _admin_dashboard():
    now = datetime.now(timezone.utc)

    total_tenders = Tender.query.count()
    active_tenders = Tender.query.filter_by(status=TenderStatus.PUBLISHED).count()
    pending_evaluation = Tender.query.filter_by(
        status=TenderStatus.UNDER_EVALUATION).count()
    awarded = Tender.query.filter_by(status=TenderStatus.AWARDED).count()

    recent_tenders = (Tender.query
                      .filter_by(admin_id=current_user.id)
                      .order_by(Tender.created_at.desc())
                      .limit(8).all())

    closing_soon = (Tender.query
                    .filter(Tender.status == TenderStatus.PUBLISHED,
                            Tender.bid_end_date >= now)
                    .order_by(Tender.bid_end_date.asc())
                    .limit(5).all())

    total_vendors = User.query.filter_by(role=UserRole.VENDOR, is_active=True).count()
    total_bids = Bid.query.count()

    return render_template('dashboard/admin.html',
                           total_tenders=total_tenders,
                           active_tenders=active_tenders,
                           pending_evaluation=pending_evaluation,
                           awarded=awarded,
                           recent_tenders=recent_tenders,
                           closing_soon=closing_soon,
                           total_vendors=total_vendors,
                           total_bids=total_bids)


def _vendor_dashboard():
    my_bids = (Bid.query
               .filter_by(vendor_id=current_user.id)
               .order_by(Bid.submitted_at.desc())
               .limit(5).all())

    open_tenders = (Tender.query
                    .filter_by(status=TenderStatus.PUBLISHED)
                    .order_by(Tender.bid_end_date.asc())
                    .limit(6).all())

    stats = {
        'total_bids': Bid.query.filter_by(vendor_id=current_user.id).count(),
        'awarded_bids': Bid.query.filter_by(
            vendor_id=current_user.id, status=BidStatus.AWARDED).count(),
        'pending_bids': Bid.query.filter_by(
            vendor_id=current_user.id, status=BidStatus.SUBMITTED).count(),
    }

    return render_template('dashboard/vendor.html',
                           my_bids=my_bids,
                           open_tenders=open_tenders,
                           stats=stats)


def _auditor_dashboard():
    from app.analytics.routes import _detect_fraud_signals, _get_overview_stats

    overview = _get_overview_stats()
    fraud_alerts = _detect_fraud_signals()

    recent_logs = (db.session.query(
        __import__('app.models', fromlist=['AuditLog']).AuditLog)
        .order_by(
        __import__('app.models', fromlist=['AuditLog']).AuditLog.timestamp.desc())
        .limit(10).all())

    return render_template('dashboard/auditor.html',
                           overview=overview,
                           fraud_alerts=fraud_alerts,
                           recent_logs=recent_logs)


@main_bp.route('/notifications')
@login_required
def notifications():
    notes = (Notification.query
             .filter_by(user_id=current_user.id)
             .order_by(Notification.created_at.desc())
             .limit(50).all())
    # Mark as read
    for n in notes:
        n.is_read = True
    db.session.commit()
    return render_template('main/notifications.html', notifications=notes)


@main_bp.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter_by(
        user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})
