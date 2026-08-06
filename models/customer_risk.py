from clock import utcnow
from .base import db

RISK_STATUSES = ("normal", "flagged", "under_review", "confirmed_fraud")

ACCOUNT_STATUSES = (
    "active",
    "restricted",
    "suspended",
    "blocked",
    "soft_deleted",
    "anonymized",
    "permanently_deleted",
)

CUSTOMER_RESTRICTION_TYPES = (
    "block_purchases",
    "block_cod",
    "require_prepaid",
    "require_otp",
    "require_manual_approval",
    "block_gift_card_purchase",
    "block_gift_card_redemption",
    "block_refunds_no_supervisor",
    "disable_loyalty",
    "disable_promotions",
    "disable_ai_assistant",
)

CUSTOMER_RESTRICTION_LABELS = {
    "block_purchases": "Block all purchases",
    "block_cod": "Disable cash on delivery",
    "require_prepaid": "Require prepaid payment",
    "require_otp": "Require OTP verification",
    "require_manual_approval": "Require manual order approval",
    "block_gift_card_purchase": "Block gift-card purchases",
    "block_gift_card_redemption": "Block gift-card redemption",
    "block_refunds_no_supervisor": "Block refunds without supervisor approval",
    "disable_loyalty": "Disable loyalty rewards",
    "disable_promotions": "Disable promotional offers",
    "disable_ai_assistant": "Disable AI assistant access",
}

FLAG_REASONS = (
    "repeated_fake_orders",
    "repeated_refused_deliveries",
    "payment_fraud",
    "chargeback_abuse",
    "gift_card_abuse",
    "coupon_or_referral_abuse",
    "fake_contact_details",
    "account_takeover_suspected",
    "harassment_or_threatening_behaviour",
    "multiple_linked_fraudulent_accounts",
    "other",
)

FLAG_REASON_LABELS = {
    "repeated_fake_orders": "Repeated fake orders",
    "repeated_refused_deliveries": "Repeated refused deliveries",
    "payment_fraud": "Payment fraud",
    "chargeback_abuse": "Chargeback abuse",
    "gift_card_abuse": "Gift-card abuse",
    "coupon_or_referral_abuse": "Coupon or referral abuse",
    "fake_contact_details": "Fake contact details",
    "account_takeover_suspected": "Account takeover suspected",
    "harassment_or_threatening_behaviour": "Harassment or threatening behaviour",
    "multiple_linked_fraudulent_accounts": "Multiple linked fraudulent accounts",
    "other": "Other",
}

RISK_ACTION_TYPES = (
    "flagged",
    "under_review",
    "restricted",
    "unrestricted",
    "suspended",
    "blocked",
    "fraud_confirmed",
    "restored",
    "soft_deleted",
    "deleted_restored",
    "anonymized",
    "permanently_deleted",
    "case_cleared",
    "kept_monitoring",
    "escalated",
    "notified",
    "blocklist_added",
    "blocklist_reviewed",
)

BLOCKLIST_IDENTIFIER_TYPES = (
    "mobile_hash",
    "email_hash",
    "payment_provider_ref",
    "address_fingerprint",
    "device_risk_id",
)

BLOCKLIST_STATUSES = ("pending_review", "approved", "rejected")


class CustomerRiskProfile(db.Model):
    """Per-customer risk/account-state record used by the Admin risk workflow.

    Deliberately separated from the customer-facing ``User`` row so internal
    fraud labels are never exposed to customers or other staff portals.
    """

    __tablename__ = "customer_risk_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False
    )
    risk_status = db.Column(db.String(30), default="normal", nullable=False)
    account_status = db.Column(db.String(30), default="active", nullable=False)

    case_owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    last_reviewed_at = db.Column(db.DateTime)
    last_reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    review_due_at = db.Column(db.DateTime)

    suspended_at = db.Column(db.DateTime)
    suspended_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    suspension_reason = db.Column(db.Text)
    suspended_until = db.Column(db.DateTime)

    blocked_at = db.Column(db.DateTime)
    blocked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    block_reason = db.Column(db.Text)

    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    deletion_reason = db.Column(db.Text)

    anonymized_at = db.Column(db.DateTime)
    anonymized_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    fraud_confirmed_at = db.Column(db.DateTime)
    fraud_confirmed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    session_revoked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", foreign_keys=[user_id])
    case_owner = db.relationship("User", foreign_keys=[case_owner_id])

    __table_args__ = (
        db.Index("idx_risk_profile_statuses", "risk_status", "account_status"),
    )


class CustomerRestriction(db.Model):
    """A single restriction applied to a customer with reason and duration."""

    __tablename__ = "customer_restrictions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    restriction_type = db.Column(db.String(40), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    lifted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    lifted_at = db.Column(db.DateTime)
    lifted_reason = db.Column(db.Text)

    user = db.relationship("User", foreign_keys=[user_id])
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index("idx_restriction_user_active", "user_id", "is_active"),
    )

    @property
    def is_temporary(self):
        return self.expires_at is not None


class CustomerRiskAction(db.Model):
    """Durable, non-editable history of every customer-risk admin action."""

    __tablename__ = "customer_risk_actions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action_type = db.Column(db.String(40), nullable=False)
    previous_risk_status = db.Column(db.String(30))
    new_risk_status = db.Column(db.String(30))
    previous_account_status = db.Column(db.String(30))
    new_account_status = db.Column(db.String(30))
    reason_category = db.Column(db.String(60))
    reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    evidence = db.Column(db.Text)
    order_ids = db.Column(db.Text)
    payment_refs = db.Column(db.Text)
    ip_address = db.Column(db.String(60))
    approval_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approval_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    admin = db.relationship("User", foreign_keys=[admin_id])
    approver = db.relationship("User", foreign_keys=[approval_by])

    __table_args__ = (
        db.Index("idx_risk_action_user_created", "user_id", "created_at"),
        db.Index("idx_risk_action_type_created", "action_type", "created_at"),
    )


class FraudBlocklistEntry(db.Model):
    """Protected identifier blocklist for confirmed fraud prevention.

    Only irreversible hashes (or provider-supplied opaque references) are
    stored. Raw personal identifiers are never persisted here and raw values
    are never rendered in the frontend.
    """

    __tablename__ = "fraud_blocklist_entries"

    id = db.Column(db.Integer, primary_key=True)
    identifier_type = db.Column(db.String(40), nullable=False)
    identifier_hash = db.Column(db.String(128), nullable=False)
    reason = db.Column(db.Text)
    case_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    status = db.Column(db.String(30), default="pending_review", nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    match_count = db.Column(db.Integer, default=0)

    case_user = db.relationship("User", foreign_keys=[case_user_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        db.UniqueConstraint(
            "identifier_type", "identifier_hash", name="uq_blocklist_identifier"
        ),
    )
