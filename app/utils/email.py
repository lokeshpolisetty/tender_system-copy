"""
Email and push notification utilities.
Upgraded: uses Amazon SES (via boto3) instead of Flask-Mail SMTP.
         uses Amazon SNS for topic-based fan-out to all vendors.

Falls back to Flask-Mail when USE_SES=false (local dev).
"""

import json
import logging
from typing import Optional

from flask import current_app, render_template, url_for

from app import db
from app.models import Notification, User, UserRole

logger = logging.getLogger(__name__)


# ─────────────────────────── Core send helpers ────────────────────────────────

def _send_ses(subject: str, recipients: list, html_body: str,
              text_body: Optional[str] = None) -> bool:
    """Send email via Amazon SES."""
    try:
        import boto3
        region = current_app.config.get('AWS_SES_REGION',
                                        current_app.config.get('AWS_S3_REGION', 'ap-south-1'))
        ses = boto3.client('ses', region_name=region)
        sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@tender.gov.in')

        body = {'Html': {'Charset': 'UTF-8', 'Data': html_body}}
        if text_body:
            body['Text'] = {'Charset': 'UTF-8', 'Data': text_body}

        ses.send_email(
            Source=sender,
            Destination={'ToAddresses': recipients},
            Message={
                'Subject': {'Charset': 'UTF-8', 'Data': subject},
                'Body': body,
            },
        )
        logger.info(f'SES email sent to {recipients}: {subject}')
        return True
    except Exception as e:
        logger.error(f'SES send failed to {recipients}: {e}')
        return False


def _send_smtp(subject: str, recipients: list, html_body: str,
               text_body: Optional[str] = None) -> bool:
    """Fallback: send via Flask-Mail SMTP."""
    try:
        from app import mail
        from flask_mail import Message
        msg = Message(subject=subject, recipients=recipients)
        msg.html = html_body
        if text_body:
            msg.body = text_body
        mail.send(msg)
        return True
    except Exception as e:
        logger.error(f'SMTP send failed to {recipients}: {e}')
        return False


def _send(subject: str, recipients: list, html_body: str,
          text_body: Optional[str] = None) -> bool:
    """Route to SES or SMTP based on config."""
    if current_app.config.get('USE_SES', False):
        return _send_ses(subject, recipients, html_body, text_body)
    return _send_smtp(subject, recipients, html_body, text_body)


def _publish_sns(topic_arn: str, message: str, subject: str) -> bool:
    """Publish a message to an SNS topic (fan-out to all subscribers)."""
    try:
        import boto3
        region = current_app.config.get('AWS_SNS_REGION',
                                        current_app.config.get('AWS_S3_REGION', 'ap-south-1'))
        sns = boto3.client('sns', region_name=region)
        sns.publish(TopicArn=topic_arn, Message=message, Subject=subject[:100])
        logger.info(f'SNS published to {topic_arn}')
        return True
    except Exception as e:
        logger.error(f'SNS publish failed: {e}')
        return False


def _create_notification(user_id: int, title: str, message: str,
                          notification_type: str = 'info',
                          related_resource: Optional[str] = None):
    try:
        note = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            related_resource=related_resource,
        )
        db.session.add(note)
        db.session.commit()
    except Exception as e:
        logger.error(f'Notification creation failed: {e}')
        db.session.rollback()


# ─────────────────────────── Auth emails ──────────────────────────────────────

def send_email_verification(user, token: str) -> bool:
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    html = render_template('emails/verify_email.html',
                           user=user, verify_url=verify_url)
    return _send(
        subject='Verify your email — Gov Tender Portal',
        recipients=[user.email],
        html_body=html,
        text_body=f'Click to verify: {verify_url}',
    )


def send_password_reset_email(user, token: str) -> bool:
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    html = render_template('emails/password_reset.html',
                           user=user, reset_url=reset_url)
    return _send(
        subject='Password Reset — Gov Tender Portal',
        recipients=[user.email],
        html_body=html,
        text_body=f'Reset your password: {reset_url}',
    )


# ─────────────────────────── Tender notifications ─────────────────────────────

def notify_vendors_tender_published(tender) -> None:
    """
    Publish to SNS topic (fan-out) + individual SES emails to all vendors.
    SNS handles scale; per-vendor SES handles personalised content.
    """
    tender_url = url_for('tenders.detail', tender_id=tender.id, _external=True)

    # SNS fan-out for real-time subscribers (mobile push, Lambda hooks, etc.)
    sns_topic = current_app.config.get('SNS_TENDER_PUBLISHED_TOPIC_ARN')
    if sns_topic:
        _publish_sns(
            topic_arn=sns_topic,
            message=json.dumps({
                'event': 'TENDER_PUBLISHED',
                'tender_id': tender.id,
                'tender_number': tender.tender_number,
                'title': tender.title,
                'category': tender.category,
                'estimated_budget': tender.estimated_budget,
                'bid_end_date': tender.bid_end_date.isoformat() if tender.bid_end_date else None,
                'url': tender_url,
            }),
            subject=f'New Tender Published: {tender.tender_number}',
        )

    # Individual emails
    vendors = User.query.filter_by(role=UserRole.VENDOR, is_active=True).all()
    for vendor in vendors:
        try:
            html = render_template('emails/tender_published.html',
                                   user=vendor, tender=tender,
                                   tender_url=tender_url)
            _send(
                subject=f'New Tender: {tender.tender_number} — {tender.title[:60]}',
                recipients=[vendor.email],
                html_body=html,
            )
            _create_notification(
                user_id=vendor.id,
                title='New Tender Published',
                message=f'Tender {tender.tender_number}: {tender.title} is now open.',
                notification_type='info',
                related_resource=f'tender:{tender.id}',
            )
        except Exception as e:
            logger.warning(f'Vendor notification failed for {vendor.email}: {e}')


def send_bid_confirmation(bid) -> bool:
    tender_url = url_for('tenders.detail',
                         tender_id=bid.tender_id, _external=True)
    html = render_template('emails/bid_submitted.html',
                           user=bid.vendor, bid=bid,
                           tender=bid.tender, tender_url=tender_url)
    ok = _send(
        subject=f'Bid Submitted — Tender {bid.tender.tender_number}',
        recipients=[bid.vendor.email],
        html_body=html,
    )
    _create_notification(
        user_id=bid.vendor_id,
        title='Bid Submitted Successfully',
        message=f'Your bid for tender {bid.tender.tender_number} has been received.',
        notification_type='success',
        related_resource=f'bid:{bid.id}',
    )
    return ok


def send_award_notification(winning_bid) -> bool:
    html = render_template('emails/bid_awarded.html',
                           user=winning_bid.vendor,
                           bid=winning_bid,
                           tender=winning_bid.tender)
    ok = _send(
        subject=f'Contract Awarded — Tender {winning_bid.tender.tender_number}',
        recipients=[winning_bid.vendor.email],
        html_body=html,
    )

    # SNS notification for award event
    sns_topic = current_app.config.get('SNS_BID_AWARDED_TOPIC_ARN')
    if sns_topic:
        _publish_sns(
            topic_arn=sns_topic,
            message=json.dumps({
                'event': 'BID_AWARDED',
                'bid_id': winning_bid.id,
                'tender_id': winning_bid.tender_id,
                'tender_number': winning_bid.tender.tender_number,
                'vendor_id': winning_bid.vendor_id,
            }),
            subject=f'Contract Awarded: {winning_bid.tender.tender_number}',
        )

    _create_notification(
        user_id=winning_bid.vendor_id,
        title='Contract Awarded!',
        message=(f'Congratulations! You have been awarded the contract for '
                 f'tender {winning_bid.tender.tender_number}.'),
        notification_type='success',
        related_resource=f'bid:{winning_bid.id}',
    )
    return ok


def send_tender_cancelled_notification(tender) -> None:
    """Notify all bidders when a tender is cancelled."""
    from app.models import Bid
    bids = Bid.query.filter_by(tender_id=tender.id).all()
    vendor_ids = {b.vendor_id for b in bids}
    vendors = User.query.filter(User.id.in_(vendor_ids)).all()
    for vendor in vendors:
        try:
            _send(
                subject=f'Tender Cancelled — {tender.tender_number}',
                recipients=[vendor.email],
                html_body=render_template(
                    'emails/tender_published.html',   # Reuse template with cancelled context
                    user=vendor, tender=tender, tender_url='', cancelled=True),
            )
            _create_notification(
                user_id=vendor.id,
                title='Tender Cancelled',
                message=f'Tender {tender.tender_number} has been cancelled.',
                notification_type='warning',
                related_resource=f'tender:{tender.id}',
            )
        except Exception as e:
            logger.warning(f'Cancellation notification failed for {vendor.email}: {e}')


def send_bid_rejected_notification(bid) -> bool:
    """Notify vendor when their bid is rejected/disqualified."""
    _create_notification(
        user_id=bid.vendor_id,
        title='Bid Update',
        message=f'Your bid for tender {bid.tender.tender_number} has been reviewed.',
        notification_type='info',
        related_resource=f'bid:{bid.id}',
    )
    return _send(
        subject=f'Bid Status Update — Tender {bid.tender.tender_number}',
        recipients=[bid.vendor.email],
        html_body=render_template('emails/bid_submitted.html',
                                  user=bid.vendor, bid=bid,
                                  tender=bid.tender, tender_url=''),
    )
