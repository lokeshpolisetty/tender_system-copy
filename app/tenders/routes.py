"""Tender management blueprint."""

import json
from datetime import datetime, timezone

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_

from app import db
from app.models import (AuditAction, Bid, BidStatus, Tender, TenderDocument,
                        TenderStatus, UserRole)
from app.utils.audit import log_action
from app.utils.decorators import role_required
from app.utils.email import notify_vendors_tender_published
from app.utils.file_handler import save_uploaded_file

tenders_bp = Blueprint('tenders', __name__)


# ─────────────────────────── Public Listing ───────────────────────────────────

@tenders_bp.route('/')
def list_tenders():
    """Public tender listing with search & filter."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    status_filter = request.args.get('status', 'published').strip()
    sort = request.args.get('sort', 'newest')

    query = Tender.query

    # Status filter
    if status_filter == 'open':
        now = datetime.now(timezone.utc)
        query = query.filter(
            Tender.status == TenderStatus.PUBLISHED,
            Tender.bid_start_date <= now,
            Tender.bid_end_date >= now
        )
    elif status_filter == 'published':
        query = query.filter(Tender.status == TenderStatus.PUBLISHED)
    elif status_filter == 'awarded':
        query = query.filter(Tender.status == TenderStatus.AWARDED)
    elif status_filter == 'all' and current_user.is_authenticated and current_user.is_admin:
        pass  # admins can see all
    else:
        query = query.filter(Tender.status == TenderStatus.PUBLISHED)

    # Text search
    if search:
        query = query.filter(or_(
            Tender.title.ilike(f'%{search}%'),
            Tender.description.ilike(f'%{search}%'),
            Tender.tender_number.ilike(f'%{search}%'),
            Tender.department.ilike(f'%{search}%'),
        ))

    if category:
        query = query.filter(Tender.category.ilike(f'%{category}%'))

    # Sort
    if sort == 'deadline':
        query = query.order_by(Tender.bid_end_date.asc())
    elif sort == 'budget_high':
        query = query.order_by(Tender.estimated_budget.desc())
    elif sort == 'budget_low':
        query = query.order_by(Tender.estimated_budget.asc())
    else:
        query = query.order_by(Tender.created_at.desc())

    per_page = current_app.config['TENDERS_PER_PAGE']
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Categories for filter dropdown
    categories = db.session.query(Tender.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    return render_template('tenders/list.html',
                           tenders=pagination.items,
                           pagination=pagination,
                           search=search,
                           category=category,
                           status_filter=status_filter,
                           sort=sort,
                           categories=categories)


@tenders_bp.route('/<int:tender_id>')
def detail(tender_id):
    """Tender detail page."""
    tender = Tender.query.get_or_404(tender_id)

    # Non-admins only see published tenders
    if not (current_user.is_authenticated and current_user.is_admin):
        if tender.status not in [TenderStatus.PUBLISHED, TenderStatus.CLOSED,
                                  TenderStatus.AWARDED, TenderStatus.UNDER_EVALUATION]:
            abort(404)

    # Check if current vendor has already bid
    vendor_bid = None
    if current_user.is_authenticated and current_user.is_vendor:
        vendor_bid = Bid.query.filter_by(
            tender_id=tender_id, vendor_id=current_user.id).first()

    documents = TenderDocument.query.filter_by(tender_id=tender_id).all()

    return render_template('tenders/detail.html',
                           tender=tender,
                           vendor_bid=vendor_bid,
                           documents=documents)


# ─────────────────────────── Admin: CRUD ──────────────────────────────────────

@tenders_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(UserRole.ADMIN)
def create():
    """Create new tender (Admin only)."""
    if request.method == 'POST':
        try:
            # Build eligibility criteria dict
            eligibility = {
                'min_experience_years': request.form.get('min_experience', ''),
                'min_turnover': request.form.get('min_turnover', ''),
                'required_certifications': request.form.get('certifications', ''),
                'other': request.form.get('other_criteria', ''),
            }

            # Parse dates
            def parse_dt(field):
                val = request.form.get(field, '')
                if not val:
                    return None
                return datetime.strptime(val, '%Y-%m-%dT%H:%M')

            tender = Tender(
                tender_number=_generate_tender_number(),
                title=request.form['title'].strip(),
                description=request.form['description'].strip(),
                category=request.form.get('category', '').strip(),
                department=request.form.get('department', '').strip(),
                location=request.form.get('location', '').strip(),
                estimated_budget=float(request.form['estimated_budget']),
                emd_amount=float(request.form.get('emd_amount') or 0),
                tender_fee=float(request.form.get('tender_fee') or 0),
                bid_start_date=parse_dt('bid_start_date'),
                bid_end_date=parse_dt('bid_end_date'),
                opening_date=parse_dt('opening_date'),
                pre_bid_meeting=parse_dt('pre_bid_meeting'),
                contact_name=request.form.get('contact_name', '').strip(),
                contact_email=request.form.get('contact_email', '').strip(),
                contact_phone=request.form.get('contact_phone', '').strip(),
                evaluation_method=request.form.get('evaluation_method', 'L1'),
                eligibility_criteria=json.dumps(eligibility),
                status=TenderStatus.DRAFT,
                admin_id=current_user.id,
            )
            db.session.add(tender)
            db.session.flush()  # Get ID before commit

            # Handle document uploads
            files = request.files.getlist('documents')
            for f in files:
                if f and f.filename:
                    file_path = save_uploaded_file(
                        f, subfolder='tenders',
                        allowed_extensions={'pdf', 'docx'})
                    if file_path:
                        doc = TenderDocument(
                            tender_id=tender.id,
                            filename=file_path.split('/')[-1],
                            original_filename=f.filename,
                            file_path=file_path,
                            file_type=f.filename.rsplit('.', 1)[-1].lower(),
                            description=request.form.get('doc_description', ''),
                            uploaded_by=current_user.id,
                        )
                        db.session.add(doc)

            db.session.commit()

            log_action(AuditAction.TENDER_CREATE, user_id=current_user.id,
                       resource_type='tender', resource_id=tender.id,
                       description=f'Tender created: {tender.tender_number} - {tender.title}')

            flash(f'Tender {tender.tender_number} created successfully.', 'success')
            return redirect(url_for('tenders.detail', tender_id=tender.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Tender creation error: {e}')
            flash(f'Error creating tender: {str(e)}', 'danger')

    return render_template('tenders/create.html')


@tenders_bp.route('/<int:tender_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(UserRole.ADMIN)
def edit(tender_id):
    """Edit tender (Admin, draft/unpublished only)."""
    tender = Tender.query.get_or_404(tender_id)

    if tender.status not in [TenderStatus.DRAFT]:
        flash('Only draft tenders can be edited.', 'warning')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    if request.method == 'POST':
        try:
            def parse_dt(field):
                val = request.form.get(field, '')
                return datetime.strptime(val, '%Y-%m-%dT%H:%M') if val else None

            tender.title = request.form['title'].strip()
            tender.description = request.form['description'].strip()
            tender.category = request.form.get('category', '')
            tender.department = request.form.get('department', '')
            tender.location = request.form.get('location', '')
            tender.estimated_budget = float(request.form['estimated_budget'])
            tender.emd_amount = float(request.form.get('emd_amount') or 0)
            tender.bid_start_date = parse_dt('bid_start_date')
            tender.bid_end_date = parse_dt('bid_end_date')
            tender.opening_date = parse_dt('opening_date')
            tender.contact_name = request.form.get('contact_name', '')
            tender.contact_email = request.form.get('contact_email', '')
            tender.contact_phone = request.form.get('contact_phone', '')
            tender.evaluation_method = request.form.get('evaluation_method', 'L1')

            db.session.commit()

            log_action(AuditAction.TENDER_UPDATE, user_id=current_user.id,
                       resource_type='tender', resource_id=tender.id,
                       description=f'Tender updated: {tender.tender_number}')

            flash('Tender updated successfully.', 'success')
            return redirect(url_for('tenders.detail', tender_id=tender.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating tender: {str(e)}', 'danger')

    return render_template('tenders/edit.html', tender=tender)


@tenders_bp.route('/<int:tender_id>/publish', methods=['POST'])
@login_required
@role_required(UserRole.ADMIN)
def publish(tender_id):
    """Publish a draft tender."""
    tender = Tender.query.get_or_404(tender_id)

    if tender.status != TenderStatus.DRAFT:
        flash('Only draft tenders can be published.', 'warning')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    tender.status = TenderStatus.PUBLISHED
    tender.published_at = datetime.now(timezone.utc)
    db.session.commit()

    log_action(AuditAction.TENDER_PUBLISH, user_id=current_user.id,
               resource_type='tender', resource_id=tender.id,
               description=f'Tender published: {tender.tender_number}')

    # Notify registered vendors
    try:
        notify_vendors_tender_published(tender)
    except Exception as e:
        current_app.logger.warning(f'Notification failed: {e}')

    flash(f'Tender {tender.tender_number} published successfully.', 'success')
    return redirect(url_for('tenders.detail', tender_id=tender_id))


@tenders_bp.route('/<int:tender_id>/cancel', methods=['POST'])
@login_required
@role_required(UserRole.ADMIN)
def cancel(tender_id):
    """Cancel a tender."""
    tender = Tender.query.get_or_404(tender_id)

    if tender.status in [TenderStatus.AWARDED, TenderStatus.CANCELLED]:
        flash('Cannot cancel an awarded or already-cancelled tender.', 'warning')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    tender.status = TenderStatus.CANCELLED
    db.session.commit()

    log_action(AuditAction.TENDER_CANCEL, user_id=current_user.id,
               resource_type='tender', resource_id=tender.id,
               description=f'Tender cancelled: {tender.tender_number}')

    flash('Tender cancelled.', 'info')
    return redirect(url_for('tenders.detail', tender_id=tender_id))


@tenders_bp.route('/documents/<int:doc_id>/download')
@login_required
def download_document(doc_id):
    """Download a tender document."""
    doc = TenderDocument.query.get_or_404(doc_id)
    upload_folder = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(
        directory=upload_folder,
        path=doc.file_path.replace(upload_folder + '/', ''),
        as_attachment=True,
        download_name=doc.original_filename
    )


# ─────────────────────────── Admin: Bid Opening ───────────────────────────────

@tenders_bp.route('/<int:tender_id>/open-bids', methods=['POST'])
@login_required
@role_required(UserRole.ADMIN)
def open_bids(tender_id):
    """Open and reveal all bids for a closed tender."""
    from app.utils.bid_processor import reveal_and_rank_bids

    tender = Tender.query.get_or_404(tender_id)
    now = datetime.now(timezone.utc)

    # Enforce: can only open after submission deadline
    end = tender.bid_end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    if now < end:
        flash('Cannot open bids before the submission deadline.', 'danger')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    if tender.status not in [TenderStatus.PUBLISHED, TenderStatus.CLOSED]:
        flash('Bids can only be opened for published or closed tenders.', 'warning')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    try:
        reveal_and_rank_bids(tender)
        tender.status = TenderStatus.UNDER_EVALUATION
        db.session.commit()

        log_action(AuditAction.BID_OPEN, user_id=current_user.id,
                   resource_type='tender', resource_id=tender.id,
                   description=f'Bids opened for tender: {tender.tender_number}')

        flash('Bids opened and ranked successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Bid opening error: {e}')
        flash(f'Error opening bids: {str(e)}', 'danger')

    return redirect(url_for('tenders.evaluation', tender_id=tender_id))


@tenders_bp.route('/<int:tender_id>/evaluation')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def evaluation(tender_id):
    """Bid evaluation page — shows ranked bids."""
    tender = Tender.query.get_or_404(tender_id)

    bids = (Bid.query
            .filter_by(tender_id=tender_id)
            .filter(Bid.is_revealed == True)
            .order_by(Bid.rank.asc())
            .all())

    return render_template('tenders/evaluation.html', tender=tender, bids=bids)


@tenders_bp.route('/<int:tender_id>/award/<int:bid_id>', methods=['POST'])
@login_required
@role_required(UserRole.ADMIN)
def award_bid(tender_id, bid_id):
    """Award tender to a specific bid."""
    from app.utils.email import send_award_notification

    tender = Tender.query.get_or_404(tender_id)
    winning_bid = Bid.query.get_or_404(bid_id)

    if winning_bid.tender_id != tender_id:
        abort(400)

    # Mark winning bid
    winning_bid.status = BidStatus.AWARDED
    # Reject all others
    other_bids = Bid.query.filter(
        Bid.tender_id == tender_id, Bid.id != bid_id).all()
    for b in other_bids:
        b.status = BidStatus.REJECTED

    tender.status = TenderStatus.AWARDED
    db.session.commit()

    try:
        send_award_notification(winning_bid)
    except Exception as e:
        current_app.logger.warning(f'Award notification failed: {e}')

    log_action(AuditAction.BID_AWARD, user_id=current_user.id,
               resource_type='bid', resource_id=bid_id,
               description=f'Bid {bid_id} awarded for tender {tender.tender_number}')

    flash(f'Contract awarded to {winning_bid.vendor.name}.', 'success')
    return redirect(url_for('tenders.evaluation', tender_id=tender_id))


# ─────────────────────────── Helpers ─────────────────────────────────────────

def _generate_tender_number() -> str:
    """Generate unique tender number: GOV-YYYY-NNNN."""
    year = datetime.now().year
    last = (Tender.query
            .filter(Tender.tender_number.like(f'GOV-{year}-%'))
            .order_by(Tender.id.desc())
            .first())
    if last:
        seq = int(last.tender_number.split('-')[-1]) + 1
    else:
        seq = 1
    return f'GOV-{year}-{seq:04d}'
