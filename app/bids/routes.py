"""Bid submission, viewing, and document upload blueprint."""

import os
from datetime import datetime, timezone

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required

from app import db
from app.models import (AuditAction, Bid, BidDocument, BidStatus, Tender,
                        TenderStatus, UserRole)
from app.utils.audit import log_action
from app.utils.bid_encryption import decrypt_bid_amount, encrypt_bid_amount
from app.utils.decorators import role_required
from app.utils.doc_processor import extract_document_data
from app.utils.email import send_bid_confirmation
from app.utils.file_handler import save_uploaded_file

bids_bp = Blueprint('bids', __name__)


@bids_bp.route('/submit/<int:tender_id>', methods=['GET', 'POST'])
@login_required
@role_required(UserRole.VENDOR)
def submit(tender_id):
    """Submit a bid for a tender."""
    tender = Tender.query.get_or_404(tender_id)

    # Validate tender is open
    if not tender.is_open_for_bidding:
        flash('This tender is not open for bidding.', 'danger')
        return redirect(url_for('tenders.detail', tender_id=tender_id))

    # Check if already submitted
    existing = Bid.query.filter_by(
        tender_id=tender_id, vendor_id=current_user.id).first()
    if existing:
        flash('You have already submitted a bid for this tender.', 'warning')
        return redirect(url_for('bids.view', bid_id=existing.id))

    if request.method == 'POST':
        try:
            bid_amount = float(request.form['bid_amount'])
            if bid_amount <= 0:
                flash('Bid amount must be positive.', 'danger')
                return render_template('bids/submit.html', tender=tender)

            # Encrypt bid amount (revealed only after opening)
            encrypted_amount = encrypt_bid_amount(bid_amount)

            bid = Bid(
                tender_id=tender_id,
                vendor_id=current_user.id,
                bid_amount_encrypted=encrypted_amount,
                bid_amount=None,            # Not revealed yet
                is_revealed=False,
                cover_letter=request.form.get('cover_letter', '').strip(),
                status=BidStatus.SUBMITTED,
                submitted_at=datetime.now(timezone.utc),
            )
            db.session.add(bid)
            db.session.flush()  # Get bid.id

            # Process uploaded documents
            extracted_data = {}
            files = request.files.getlist('documents')
            for f in files:
                if f and f.filename:
                    ext = f.filename.rsplit('.', 1)[-1].lower()
                    file_path = save_uploaded_file(
                        f, subfolder=f'bids/{bid.id}',
                        allowed_extensions={'pdf', 'docx'})
                    if file_path:
                        # Extract data from document
                        doc_data = extract_document_data(file_path)
                        extracted_data.update(doc_data)

                        category = request.form.get(f'doc_category_{f.filename}', 'other')
                        bd = BidDocument(
                            bid_id=bid.id,
                            filename=file_path.split('/')[-1],
                            original_filename=f.filename,
                            file_path=file_path,
                            file_type=ext,
                            file_size=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                            doc_category=category,
                        )
                        db.session.add(bd)

            import json
            bid.extracted_data = json.dumps(extracted_data)
            db.session.commit()

            log_action(AuditAction.BID_SUBMIT, user_id=current_user.id,
                       resource_type='bid', resource_id=bid.id,
                       description=f'Bid submitted for tender {tender.tender_number} by {current_user.email}')

            try:
                send_bid_confirmation(bid)
            except Exception as e:
                current_app.logger.warning(f'Bid confirmation email failed: {e}')

            flash('Bid submitted successfully! Your bid is encrypted and secured.', 'success')
            return redirect(url_for('bids.view', bid_id=bid.id))

        except ValueError as ve:
            db.session.rollback()
            flash(f'Invalid data: {str(ve)}', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Bid submission error: {e}')
            flash(f'Error submitting bid: {str(e)}', 'danger')

    return render_template('bids/submit.html', tender=tender)


@bids_bp.route('/<int:bid_id>')
@login_required
def view(bid_id):
    """View a single bid."""
    bid = Bid.query.get_or_404(bid_id)

    # Access control: vendor sees own bids; admin/auditor sees all
    if current_user.is_vendor and bid.vendor_id != current_user.id:
        abort(403)

    documents = BidDocument.query.filter_by(bid_id=bid_id).all()
    return render_template('bids/view.html', bid=bid, documents=documents)


@bids_bp.route('/my-bids')
@login_required
@role_required(UserRole.VENDOR)
def my_bids():
    """Vendor: list all their submitted bids."""
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['BIDS_PER_PAGE']

    bids_q = (Bid.query
              .filter_by(vendor_id=current_user.id)
              .order_by(Bid.submitted_at.desc())
              .paginate(page=page, per_page=per_page, error_out=False))

    return render_template('bids/my_bids.html', bids=bids_q.items,
                           pagination=bids_q)


@bids_bp.route('/tender/<int:tender_id>/all')
@login_required
@role_required(UserRole.ADMIN, UserRole.AUDITOR)
def all_bids_for_tender(tender_id):
    """Admin/Auditor: view all bids for a tender (amounts hidden until opened)."""
    tender = Tender.query.get_or_404(tender_id)
    bids = (Bid.query
            .filter_by(tender_id=tender_id)
            .order_by(Bid.submitted_at.asc())
            .all())

    return render_template('bids/all_bids.html', tender=tender, bids=bids)


@bids_bp.route('/<int:bid_id>/documents/<int:doc_id>/download')
@login_required
def download_doc(bid_id, doc_id):
    """Download a bid document."""
    bid = Bid.query.get_or_404(bid_id)
    doc = BidDocument.query.get_or_404(doc_id)

    if doc.bid_id != bid_id:
        abort(400)

    # Access control
    if current_user.is_vendor and bid.vendor_id != current_user.id:
        abort(403)

    # Auditors/admins can only access documents after bids are opened
    if (current_user.is_auditor or current_user.is_admin) and not bid.is_revealed:
        flash('Bid documents are sealed until bids are officially opened.', 'warning')
        return redirect(url_for('bids.all_bids_for_tender', tender_id=bid.tender_id))

    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_dir = os.path.dirname(doc.file_path)
    filename = os.path.basename(doc.file_path)

    return send_from_directory(
        directory=file_dir,
        path=filename,
        as_attachment=True,
        download_name=doc.original_filename
    )


@bids_bp.route('/<int:bid_id>/withdraw', methods=['POST'])
@login_required
@role_required(UserRole.VENDOR)
def withdraw(bid_id):
    """Vendor withdraws a bid (only before deadline)."""
    bid = Bid.query.get_or_404(bid_id)

    if bid.vendor_id != current_user.id:
        abort(403)

    tender = bid.tender
    if not tender.is_open_for_bidding:
        flash('Cannot withdraw bid after deadline.', 'danger')
        return redirect(url_for('bids.view', bid_id=bid_id))

    db.session.delete(bid)
    db.session.commit()

    flash('Bid withdrawn successfully.', 'info')
    return redirect(url_for('bids.my_bids'))
