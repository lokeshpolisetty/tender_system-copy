"""
REST API blueprint (JWT-protected).
Provides programmatic access for integrations.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                get_jwt_identity, jwt_required)

from app import db
from app.models import Bid, Tender, TenderStatus, User, UserRole
from app.utils.decorators import api_role_required

api_bp = Blueprint('api', __name__)


@api_bp.route('/auth/login', methods=['POST'])
def api_login():
    """Obtain JWT tokens."""
    data = request.get_json() or {}
    email = data.get('email', '').lower().strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid credentials.'}), 401

    if not user.is_active or user.is_suspended:
        return jsonify({'error': 'Account inactive or suspended.'}), 403

    access_token = create_access_token(identity=str(user.id),
                                       additional_claims={'role': user.role.value})
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': {
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'role': user.role.value,
        }
    })


@api_bp.route('/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def api_refresh():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    access_token = create_access_token(identity=str(user.id),
                                       additional_claims={'role': user.role.value})
    return jsonify({'access_token': access_token})


@api_bp.route('/tenders', methods=['GET'])
def api_list_tenders():
    """Public: list published tenders."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    status = request.args.get('status', 'published')

    query = Tender.query.filter_by(status=TenderStatus.PUBLISHED)
    pagination = query.order_by(Tender.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    tenders_data = [{
        'id': t.id,
        'tender_number': t.tender_number,
        'title': t.title,
        'category': t.category,
        'department': t.department,
        'estimated_budget': t.estimated_budget,
        'bid_end_date': t.bid_end_date.isoformat() if t.bid_end_date else None,
        'status': t.status.value,
        'days_remaining': t.days_remaining,
        'bid_count': t.bid_count,
    } for t in pagination.items]

    return jsonify({
        'tenders': tenders_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'page': page,
    })


@api_bp.route('/tenders/<int:tender_id>', methods=['GET'])
def api_tender_detail(tender_id):
    """Public: tender detail."""
    tender = Tender.query.get_or_404(tender_id)
    if tender.status not in [TenderStatus.PUBLISHED, TenderStatus.AWARDED]:
        return jsonify({'error': 'Tender not found.'}), 404

    return jsonify({
        'id': tender.id,
        'tender_number': tender.tender_number,
        'title': tender.title,
        'description': tender.description,
        'category': tender.category,
        'department': tender.department,
        'location': tender.location,
        'estimated_budget': tender.estimated_budget,
        'emd_amount': tender.emd_amount,
        'bid_start_date': tender.bid_start_date.isoformat() if tender.bid_start_date else None,
        'bid_end_date': tender.bid_end_date.isoformat() if tender.bid_end_date else None,
        'status': tender.status.value,
        'eligibility': tender.eligibility_dict,
        'contact': {
            'name': tender.contact_name,
            'email': tender.contact_email,
            'phone': tender.contact_phone,
        }
    })


@api_bp.route('/bids', methods=['GET'])
@jwt_required()
def api_my_bids():
    """Vendor: list own bids."""
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or user.role != UserRole.VENDOR:
        return jsonify({'error': 'Vendor access required.'}), 403

    bids = Bid.query.filter_by(vendor_id=user_id).all()
    return jsonify({'bids': [{
        'id': b.id,
        'tender_id': b.tender_id,
        'tender_number': b.tender.tender_number,
        'status': b.status.value,
        'submitted_at': b.submitted_at.isoformat(),
        'is_revealed': b.is_revealed,
        'bid_amount': b.bid_amount if b.is_revealed else None,
    } for b in bids]})


@api_bp.route('/analytics/overview', methods=['GET'])
@jwt_required()
@api_role_required('admin', 'auditor')
def api_analytics():
    """Admin/Auditor: analytics overview."""
    from app.analytics.routes import _get_overview_stats
    return jsonify(_get_overview_stats())
