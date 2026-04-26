"""
Bid processor — decrypts and ranks bids after the deadline.

Called by the admin "Open Bids" action.
"""

import logging
from datetime import datetime, timezone

from app import db
from app.models import Bid, BidStatus, Tender
from app.utils.bid_encryption import decrypt_bid_amount

logger = logging.getLogger(__name__)


def reveal_and_rank_bids(tender: Tender) -> None:
    """
    Decrypt all submitted bids for a tender, rank them by amount (L1 method),
    and persist the results.

    Side-effects
    ------------
    - Sets Bid.bid_amount (decrypted float)
    - Sets Bid.is_revealed = True
    - Sets Bid.rank (1 = lowest / L1)
    - Sets Bid.is_l1 = True on the lowest bid
    - Sets Bid.opened_at
    - Commits to the database
    """
    bids = (Bid.query
            .filter_by(tender_id=tender.id)
            .filter(Bid.status == BidStatus.SUBMITTED)
            .all())

    if not bids:
        logger.info(f'No bids to reveal for tender {tender.tender_number}')
        return

    now = datetime.now(timezone.utc)
    revealed = []

    for bid in bids:
        try:
            amount = decrypt_bid_amount(bid.bid_amount_encrypted)
            bid.bid_amount = amount
            bid.is_revealed = True
            bid.opened_at = now
            bid.status = BidStatus.UNDER_REVIEW
            revealed.append(bid)
        except ValueError as e:
            logger.error(f'Could not decrypt bid {bid.id}: {e}')
            bid.status = BidStatus.DISQUALIFIED

    # Sort by amount ascending (L1 = lowest)
    revealed_sorted = sorted(revealed, key=lambda b: b.bid_amount)

    for rank, bid in enumerate(revealed_sorted, start=1):
        bid.rank = rank
        bid.is_l1 = (rank == 1)

    db.session.commit()
    logger.info(
        f'Revealed & ranked {len(revealed)} bids for tender '
        f'{tender.tender_number}. L1 amount: '
        f'{revealed_sorted[0].bid_amount if revealed_sorted else "N/A"}'
    )


def generate_evaluation_report(tender: Tender) -> dict:
    """
    Build a structured evaluation report dict for a tender.
    Used by the PDF/HTML report generator.
    """
    bids = (Bid.query
            .filter_by(tender_id=tender.id, is_revealed=True)
            .order_by(Bid.rank.asc())
            .all())

    rows = []
    for bid in bids:
        rows.append({
            'rank': bid.rank,
            'vendor_name': bid.vendor.name,
            'vendor_org': bid.vendor.organization,
            'bid_amount': bid.bid_amount,
            'is_l1': bid.is_l1,
            'status': bid.status.value,
            'submitted_at': bid.submitted_at.isoformat() if bid.submitted_at else None,
        })

    l1_bid = next((b for b in bids if b.is_l1), None)
    savings = None
    if l1_bid and tender.estimated_budget and l1_bid.bid_amount:
        savings = tender.estimated_budget - l1_bid.bid_amount
        savings_pct = (savings / tender.estimated_budget) * 100
    else:
        savings_pct = None

    return {
        'tender_number': tender.tender_number,
        'tender_title': tender.title,
        'estimated_budget': tender.estimated_budget,
        'total_bids': len(rows),
        'bids': rows,
        'l1_amount': l1_bid.bid_amount if l1_bid else None,
        'l1_vendor': l1_bid.vendor.name if l1_bid else None,
        'savings': savings,
        'savings_pct': round(savings_pct, 2) if savings_pct is not None else None,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
