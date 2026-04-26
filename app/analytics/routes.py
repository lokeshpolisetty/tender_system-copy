"""Analytics and fraud detection blueprint."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models import (AuditAction, AuditLog, Bid, BidStatus, Tender,
                        TenderStatus, User, UserRole)
from app.utils.decorators import role_required

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/dashboard')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def dashboard():
    """Main analytics dashboard."""
    stats = _get_overview_stats()
    fraud_alerts = _detect_fraud_signals()
    monthly_data = _monthly_tender_data()
    category_data = _category_distribution()
    top_vendors = _top_winning_vendors()

    return render_template('analytics/dashboard.html',
                           stats=stats,
                           fraud_alerts=fraud_alerts,
                           monthly_data=monthly_data,
                           category_data=category_data,
                           top_vendors=top_vendors)


@analytics_bp.route('/audit-log')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def audit_log():
    """Audit trail viewer."""
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user_id', '', type=str)

    from flask import current_app
    per_page = current_app.config['LOGS_PER_PAGE']

    query = AuditLog.query.order_by(AuditLog.timestamp.desc())

    if action_filter:
        try:
            query = query.filter(AuditLog.action == AuditAction(action_filter))
        except ValueError:
            pass

    if user_filter and user_filter.isdigit():
        query = query.filter(AuditLog.user_id == int(user_filter))

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Verify hash chain integrity
    integrity_ok = _verify_log_integrity(pagination.items)

    actions = [a.value for a in AuditAction]
    users = User.query.order_by(User.name).all()

    return render_template('analytics/audit_log.html',
                           logs=pagination.items,
                           pagination=pagination,
                           actions=actions,
                           users=users,
                           action_filter=action_filter,
                           user_filter=user_filter,
                           integrity_ok=integrity_ok)


@analytics_bp.route('/fraud-detection')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def fraud_detection():
    """Detailed fraud / cartelization analysis."""
    alerts = _detect_fraud_signals(detailed=True)
    return render_template('analytics/fraud_detection.html', alerts=alerts)


@analytics_bp.route('/api/chart-data')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def chart_data():
    """JSON endpoint for Chart.js data."""
    chart_type = request.args.get('type', 'monthly')

    if chart_type == 'monthly':
        return jsonify(_monthly_tender_data())
    elif chart_type == 'category':
        return jsonify(_category_distribution())
    elif chart_type == 'budget':
        return jsonify(_budget_utilization())
    else:
        return jsonify({'error': 'Unknown chart type'}), 400


# ─────────────────────────── Internal helpers ─────────────────────────────────

def _get_overview_stats() -> dict:
    total_tenders = Tender.query.count()
    active_tenders = Tender.query.filter_by(status=TenderStatus.PUBLISHED).count()
    awarded_tenders = Tender.query.filter_by(status=TenderStatus.AWARDED).count()
    total_vendors = User.query.filter_by(role=UserRole.VENDOR).count()
    total_bids = Bid.query.count()

    total_awarded_value = (
        db.session.query(func.sum(Bid.bid_amount))
        .filter(Bid.status == BidStatus.AWARDED)
        .scalar() or 0
    )

    return {
        'total_tenders': total_tenders,
        'active_tenders': active_tenders,
        'awarded_tenders': awarded_tenders,
        'total_vendors': total_vendors,
        'total_bids': total_bids,
        'total_awarded_value': total_awarded_value,
    }


def _detect_fraud_signals(detailed: bool = False) -> list:
    """
    Fraud detection heuristics:
    1. Cartelization: bids within 1% of each other on same tender
    2. Repeated winner: same vendor wins > 3 tenders
    3. Suspiciously low bid: < 50% of estimated budget
    """
    alerts = []

    # ── 1. Cartelization suspicion ─────────────────────────────────────────
    tenders_with_bids = (
        db.session.query(Bid.tender_id)
        .filter(Bid.is_revealed == True)
        .group_by(Bid.tender_id)
        .having(func.count(Bid.id) >= 2)
        .all()
    )

    for (tid,) in tenders_with_bids:
        bids = (Bid.query
                .filter_by(tender_id=tid, is_revealed=True)
                .filter(Bid.bid_amount != None)
                .all())
        amounts = [b.bid_amount for b in bids if b.bid_amount]
        if len(amounts) >= 2:
            min_a, max_a = min(amounts), max(amounts)
            if max_a > 0:
                spread_pct = ((max_a - min_a) / max_a) * 100
                if spread_pct < 1.0:  # All bids within 1%
                    tender = Tender.query.get(tid)
                    alerts.append({
                        'type': 'cartelization',
                        'severity': 'high',
                        'tender_id': tid,
                        'tender_number': tender.tender_number if tender else str(tid),
                        'message': (f'All bids for tender {tender.tender_number if tender else tid} '
                                    f'are within {spread_pct:.2f}% of each other — '
                                    f'possible bid rigging.'),
                        'detail': {'spread_pct': round(spread_pct, 3),
                                   'bid_amounts': amounts} if detailed else {},
                    })

    # ── 2. Repeated winners ────────────────────────────────────────────────
    winners = (
        db.session.query(Bid.vendor_id, func.count(Bid.id).label('wins'))
        .filter(Bid.status == BidStatus.AWARDED)
        .group_by(Bid.vendor_id)
        .having(func.count(Bid.id) > 3)
        .all()
    )
    for vendor_id, wins in winners:
        vendor = User.query.get(vendor_id)
        alerts.append({
            'type': 'repeated_winner',
            'severity': 'medium',
            'vendor_id': vendor_id,
            'message': (f'{vendor.name if vendor else vendor_id} has won '
                        f'{wins} tenders — review for preferential treatment.'),
            'detail': {'wins': wins} if detailed else {},
        })

    # ── 3. Abnormally low bids ─────────────────────────────────────────────
    low_bids = (
        db.session.query(Bid, Tender)
        .join(Tender, Bid.tender_id == Tender.id)
        .filter(Bid.is_revealed == True)
        .filter(Bid.bid_amount < Tender.estimated_budget * 0.5)
        .all()
    )
    for bid, tender in low_bids:
        pct = (bid.bid_amount / tender.estimated_budget * 100) if tender.estimated_budget else 0
        alerts.append({
            'type': 'low_bid',
            'severity': 'low',
            'bid_id': bid.id,
            'tender_id': tender.id,
            'message': (f'Bid {bid.id} for tender {tender.tender_number} is '
                        f'only {pct:.1f}% of estimated budget — verify feasibility.'),
            'detail': {'bid_amount': bid.bid_amount,
                       'budget': tender.estimated_budget} if detailed else {},
        })

    return alerts


def _monthly_tender_data() -> dict:
    """Last 12 months of tender counts."""
    now = datetime.now(timezone.utc)
    labels, counts = [], []
    for i in range(11, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        count = Tender.query.filter(
            Tender.created_at >= month_start,
            Tender.created_at < month_end
        ).count()
        labels.append(month_start.strftime('%b %Y'))
        counts.append(count)
    return {'labels': labels, 'data': counts}


def _category_distribution() -> dict:
    rows = (db.session.query(Tender.category, func.count(Tender.id))
            .group_by(Tender.category).all())
    labels = [r[0] or 'Uncategorised' for r in rows]
    data = [r[1] for r in rows]
    return {'labels': labels, 'data': data}


def _budget_utilization() -> dict:
    rows = (db.session.query(
                Tender.category,
                func.sum(Tender.estimated_budget).label('budget'),
                func.sum(Bid.bid_amount).label('awarded'))
            .outerjoin(Bid, (Bid.tender_id == Tender.id) & (Bid.status == BidStatus.AWARDED))
            .group_by(Tender.category).all())
    return {
        'labels': [r[0] or 'Uncategorised' for r in rows],
        'budget': [float(r[1] or 0) for r in rows],
        'awarded': [float(r[2] or 0) for r in rows],
    }


def _top_winning_vendors(limit: int = 10) -> list:
    rows = (db.session.query(User.name, User.organization,
                             func.count(Bid.id).label('wins'),
                             func.sum(Bid.bid_amount).label('total_value'))
            .join(Bid, Bid.vendor_id == User.id)
            .filter(Bid.status == BidStatus.AWARDED)
            .group_by(User.id, User.name, User.organization)
            .order_by(func.count(Bid.id).desc())
            .limit(limit).all())
    return [{'name': r[0], 'org': r[1],
             'wins': r[2], 'value': float(r[3] or 0)} for r in rows]


def _verify_log_integrity(logs: list) -> bool:
    """Check hash chain continuity for displayed log entries."""
    from app.models import AuditLog as AL
    import hashlib
    for log in logs:
        record_data = (
            f"{log.action.value}|{log.user_id}|{log.resource_type}|"
            f"{log.resource_id}|{log.timestamp}|{log.description}"
        )
        expected = AL.compute_hash(record_data, log.previous_hash or '0' * 64)
        if log.entry_hash and log.entry_hash != expected:
            return False
    return True
