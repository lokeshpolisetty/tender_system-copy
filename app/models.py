"""
Database models for Government Tender & Contract Management System.
Uses SQLAlchemy ORM with PostgreSQL.
"""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum as PyEnum

from flask_login import UserMixin
from sqlalchemy import (Boolean, Column, DateTime, Enum, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, event)
from sqlalchemy.orm import relationship

from app import db, bcrypt


# ─────────────────────────── Enumerations ────────────────────────────────────

class UserRole(PyEnum):
    ADMIN = 'admin'
    VENDOR = 'vendor'
    AUDITOR = 'auditor'


class TenderStatus(PyEnum):
    DRAFT = 'draft'
    PUBLISHED = 'published'
    CLOSED = 'closed'           # Past submission deadline, not yet opened
    UNDER_EVALUATION = 'under_evaluation'
    AWARDED = 'awarded'
    CANCELLED = 'cancelled'


class BidStatus(PyEnum):
    SUBMITTED = 'submitted'
    UNDER_REVIEW = 'under_review'
    SHORTLISTED = 'shortlisted'
    AWARDED = 'awarded'
    REJECTED = 'rejected'
    DISQUALIFIED = 'disqualified'


class AuditAction(PyEnum):
    USER_REGISTER = 'user_register'
    USER_LOGIN = 'user_login'
    USER_LOGOUT = 'user_logout'
    USER_PASSWORD_RESET = 'user_password_reset'
    USER_EMAIL_VERIFY = 'user_email_verify'
    TENDER_CREATE = 'tender_create'
    TENDER_UPDATE = 'tender_update'
    TENDER_PUBLISH = 'tender_publish'
    TENDER_CANCEL = 'tender_cancel'
    BID_SUBMIT = 'bid_submit'
    BID_OPEN = 'bid_open'
    BID_EVALUATE = 'bid_evaluate'
    BID_AWARD = 'bid_award'
    DOCUMENT_UPLOAD = 'document_upload'
    REPORT_GENERATE = 'report_generate'


# ─────────────────────────── Models ──────────────────────────────────────────

class User(UserMixin, db.Model):
    """User account — supports Admin, Vendor, and Auditor roles."""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.VENDOR)

    # Profile
    organization = Column(String(200))
    phone = Column(String(20))
    address = Column(Text)
    gst_number = Column(String(20))         # GST registration for vendors
    pan_number = Column(String(10))

    # Status flags
    is_active = Column(Boolean, default=False)   # False until email verified
    is_suspended = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    email_verify_token = Column(String(200))
    email_verify_sent_at = Column(DateTime)
    password_reset_token = Column(String(200))
    password_reset_sent_at = Column(DateTime)

    # Digital signature (mock)
    digital_signature = Column(Text)            # Base64-encoded mock signature
    signature_verified = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime)

    # Relationships
    tenders = relationship('Tender', backref='created_by', lazy='dynamic',
                           foreign_keys='Tender.admin_id')
    bids = relationship('Bid', backref='vendor', lazy='dynamic',
                        foreign_keys='Bid.vendor_id')
    audit_logs = relationship('AuditLog', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def has_role(self, *roles):
        return self.role in [UserRole(r) if isinstance(r, str) else r for r in roles]

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_vendor(self):
        return self.role == UserRole.VENDOR

    @property
    def is_auditor(self):
        return self.role == UserRole.AUDITOR

    def __repr__(self):
        return f'<User {self.email} [{self.role.value}]>'


class Tender(db.Model):
    """Government tender notice."""
    __tablename__ = 'tenders'

    id = Column(Integer, primary_key=True)
    tender_number = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100))              # Works / Goods / Services
    department = Column(String(200))
    location = Column(String(200))

    # Financial
    estimated_budget = Column(Float, nullable=False)
    emd_amount = Column(Float)                  # Earnest Money Deposit
    tender_fee = Column(Float, default=0)

    # Dates
    published_at = Column(DateTime)
    bid_start_date = Column(DateTime, nullable=False)
    bid_end_date = Column(DateTime, nullable=False)   # Submission deadline
    pre_bid_meeting = Column(DateTime)
    opening_date = Column(DateTime)              # When bids are opened

    # Status
    status = Column(Enum(TenderStatus), default=TenderStatus.DRAFT, index=True)

    # Eligibility criteria (JSON stored as text)
    eligibility_criteria = Column(Text)          # JSON string

    # Contacts
    contact_name = Column(String(120))
    contact_email = Column(String(120))
    contact_phone = Column(String(20))

    # Evaluation method
    evaluation_method = Column(String(50), default='L1')  # L1 / QCBS / etc.

    # Metadata
    admin_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    documents = relationship('TenderDocument', backref='tender',
                             lazy='dynamic', cascade='all, delete-orphan')
    bids = relationship('Bid', backref='tender', lazy='dynamic',
                        cascade='all, delete-orphan')

    @staticmethod
    def _as_local_naive(dt):
        """Normalize datetimes for consistent comparisons with DB-stored naive values."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt
        return dt.astimezone().replace(tzinfo=None)

    @property
    def is_open_for_bidding(self):
        now = datetime.now()
        start = self._as_local_naive(self.bid_start_date)
        end = self._as_local_naive(self.bid_end_date)
        return (self.status == TenderStatus.PUBLISHED and
                start <= now <= end)

    @property
    def is_bidding_not_started(self):
        now = datetime.now()
        start = self._as_local_naive(self.bid_start_date)
        return self.status == TenderStatus.PUBLISHED and now < start

    @property
    def is_bidding_closed(self):
        now = datetime.now()
        end = self._as_local_naive(self.bid_end_date)
        return self.status == TenderStatus.PUBLISHED and now > end

    @property
    def days_remaining(self):
        now = datetime.now()
        end = self._as_local_naive(self.bid_end_date)
        delta = end - now
        return max(0, delta.days)

    @property
    def bid_count(self):
        return self.bids.count()

    @property
    def eligibility_dict(self):
        try:
            return json.loads(self.eligibility_criteria) if self.eligibility_criteria else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def __repr__(self):
        return f'<Tender {self.tender_number}: {self.title[:50]}>'


class TenderDocument(db.Model):
    """Documents attached to a tender notice."""
    __tablename__ = 'tender_documents'

    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    file_type = Column(String(50))
    description = Column(String(300))
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    uploaded_by = Column(Integer, ForeignKey('users.id'))


class Bid(db.Model):
    """Vendor bid submission for a tender."""
    __tablename__ = 'bids'

    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey('tenders.id'), nullable=False)
    vendor_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Bid amount — stored encrypted before opening
    bid_amount_encrypted = Column(Text)          # Fernet-encrypted amount
    bid_amount = Column(Float)                   # Revealed after opening
    is_revealed = Column(Boolean, default=False)

    # L1 determination
    is_l1 = Column(Boolean, default=False)
    rank = Column(Integer)

    # Status
    status = Column(Enum(BidStatus), default=BidStatus.SUBMITTED, index=True)

    # Submission details
    cover_letter = Column(Text)
    technical_score = Column(Float)
    financial_score = Column(Float)
    total_score = Column(Float)

    # Extracted data from documents (JSON)
    extracted_data = Column(Text)

    # Timestamps
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
    opened_at = Column(DateTime)

    # Unique constraint: one bid per vendor per tender
    __table_args__ = (UniqueConstraint('tender_id', 'vendor_id',
                                       name='uq_bid_tender_vendor'),)

    # Relationships
    documents = relationship('BidDocument', backref='bid',
                             lazy='dynamic', cascade='all, delete-orphan')

    @property
    def extracted_dict(self):
        try:
            return json.loads(self.extracted_data) if self.extracted_data else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def __repr__(self):
        return f'<Bid tender={self.tender_id} vendor={self.vendor_id}>'


class BidDocument(db.Model):
    """Documents uploaded with a bid."""
    __tablename__ = 'bid_documents'

    id = Column(Integer, primary_key=True)
    bid_id = Column(Integer, ForeignKey('bids.id'), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    file_type = Column(String(50))
    doc_category = Column(String(50))            # technical / financial / other
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    """
    Immutable audit trail.
    Each row includes a SHA-256 hash chaining it to the previous entry,
    simulating blockchain-style tamper detection.
    """
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    action = Column(Enum(AuditAction), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    resource_type = Column(String(50))           # 'tender', 'bid', 'user'
    resource_id = Column(Integer)
    description = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    extra_data = Column(Text)                    # JSON extra context

    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                       index=True)

    # Hash chain for integrity
    entry_hash = Column(String(64))              # SHA-256 of this record
    previous_hash = Column(String(64))           # SHA-256 of previous record

    @staticmethod
    def compute_hash(record_data: str, previous_hash: str) -> str:
        """Compute SHA-256 hash chaining this entry to the previous."""
        payload = f"{previous_hash}|{record_data}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def set_hash(self):
        """Generate and store entry hash."""
        # Get the previous log entry's hash
        prev = AuditLog.query.order_by(AuditLog.id.desc()).first()
        self.previous_hash = prev.entry_hash if prev else '0' * 64

        record_data = (
            f"{self.action.value}|{self.user_id}|{self.resource_type}|"
            f"{self.resource_id}|{self.timestamp}|{self.description}"
        )
        self.entry_hash = self.compute_hash(record_data, self.previous_hash)

    def __repr__(self):
        return f'<AuditLog {self.action.value} by user={self.user_id}>'


class Notification(db.Model):
    """In-app and email notifications."""
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50))       # info / success / warning / error
    is_read = Column(Boolean, default=False)
    related_resource = Column(String(100))       # e.g. 'tender:42'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship('User', backref=db.backref('notifications', lazy='dynamic'))
