"""Customer risk management service.

Implements the admin risk workflow:

    Flagged -> Under Review -> Suspended/Blocked -> Confirmed Fraud
                                -> Soft Deleted or Anonymized

Every state transition is recorded in ``CustomerRiskAction`` (durable,
non-editable) and mirrored into the system audit log. No action ever
permanently deletes a customer on suspicion alone; permanent deletion is
blocked whenever linked financial, legal, or security records exist.
"""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re

from clock import utcnow
from exceptions import ValidationError
from models import (
    CustomerRestriction,
    CustomerRiskAction,
    CustomerRiskProfile,
    FraudAlert,
    FraudBlocklistEntry,
    GiftCard,
    LoginHistory,
    Message,
    Order,
    Refund,
    Subscription,
    User,
    db,
)
from models.customer_risk import (
    ACCOUNT_STATUSES,
    BLOCKLIST_IDENTIFIER_TYPES,
    BLOCKLIST_STATUSES,
    CUSTOMER_RESTRICTION_LABELS,
    CUSTOMER_RESTRICTION_TYPES,
    FLAG_REASONS,
)
from utils.phone import digits_only, mobile_last_10, normalize_mobile

NEUTRAL_MESSAGE = (
    "Your account is temporarily unavailable. Please contact customer support."
)

BLOCKED_ACCOUNT_STATUSES = {
    "suspended",
    "blocked",
    "soft_deleted",
    "anonymized",
    "permanently_deleted",
}

TERMINAL_ORDER_STATUSES = {"CANCELLED", "REFUNDED", "DELIVERED"}
PENDING_PAYMENT_STATUSES = {"PENDING", "AUTHORIZED"}

_WHITESPACE_RE = re.compile(r"\s+")


def _anonymized_email(user_id, original_email):
    raw = f"deleted:{int(user_id)}:{str(original_email or '').lower()}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"deleted-{digest}@anonymized.invalid"


def _identifier_hash(identifier_type, value):
    raw = (value or "").strip()
    if identifier_type == "mobile_hash":
        raw = digits_only(raw)
    elif identifier_type == "email_hash":
        raw = raw.lower()
    else:
        raw = _WHITESPACE_RE.sub("", raw).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_blocklist_value(identifier_type, value):
    value = (value or "").strip()
    if identifier_type == "mobile_hash":
        normalized = normalize_mobile(value)
        if not normalized:
            raise ValidationError("Enter a valid mobile number to block.")
        return normalized
    if identifier_type == "email_hash":
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.lower()):
            raise ValidationError("Enter a valid email address to block.")
        return value.lower()
    if not value:
        raise ValidationError("Enter a value to block.")
    return value


def _client_ip():
    try:
        from flask import request

        return request.remote_addr or ""
    except Exception:
        return ""


class CustomerRiskService:
    # ── Profile helpers ────────────────────────────────────────
    def get_profile(self, user, *, create=True):
        profile = CustomerRiskProfile.query.filter_by(user_id=user.id).first()
        if profile is None and create:
            profile = CustomerRiskProfile(
                user_id=user.id,
                risk_status="normal",
                account_status="active",
            )
            db.session.add(profile)
            db.session.flush()
        return profile

    def active_restrictions(self, user):
        now = utcnow()
        return (
            CustomerRestriction.query.filter_by(user_id=user.id, is_active=True)
            .filter(
                CustomerRestriction.expires_at.is_(None)
                | (CustomerRestriction.expires_at > now)
            )
            .order_by(CustomerRestriction.created_at.desc())
            .all()
        )

    def active_restriction_map(self, user):
        return {r.restriction_type: r for r in self.active_restrictions(user)}

    def has_active_restriction(self, user, restriction_type):
        return restriction_type in self.active_restriction_map(user)

    # ── Guards (server-side enforcement) ───────────────────────
    def login_blocked_message(self, user):
        """Neutral message when login must be refused, else None."""
        if user is None:
            return None
        profile = self.get_profile(user, create=False)
        if profile is None:
            return None
        if profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        return None

    def should_block_session(self, user):
        """Force-logout for sessions started before a revocation point."""
        if user is None:
            return False
        profile = self.get_profile(user, create=False)
        if profile is None:
            return False
        if profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return True
        if profile.session_revoked_at is None:
            return False
        latest_login = (
            LoginHistory.query.filter_by(
                user_id=user.id,
                status="success",
            )
            .order_by(LoginHistory.login_time.desc())
            .first()
        )
        if latest_login is None or latest_login.login_time is None:
            return True
        return profile.session_revoked_at >= latest_login.login_time

    def purchase_error(self, user, payment_method=None):
        """Return a customer-safe error string if purchasing is blocked."""
        if user is None:
            return None
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        restrictions = self.active_restriction_map(user)
        if "block_purchases" in restrictions:
            return NEUTRAL_MESSAGE
        method = (payment_method or "").strip().upper()
        if method in {"COD", "CASH ON DELIVERY", ""} and (
            "block_cod" in restrictions or "require_prepaid" in restrictions
        ):
            return (
                "Cash on delivery is not available for this account. "
                "Please choose a prepaid payment method."
            )
        return None

    def ensure_can_purchase(self, user, payment_method=None):
        error = self.purchase_error(user, payment_method=payment_method)
        if error:
            raise ValidationError(error)
        return True

    def order_needs_manual_approval(self, user):
        restrictions = self.active_restriction_map(user)
        return (
            "require_manual_approval" in restrictions
            or "require_otp" in restrictions
        )

    def ai_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "disable_ai_assistant"):
            return "This assistant is not available right now. Please try again later."
        return None

    def loyalty_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "disable_loyalty"):
            return "Loyalty rewards are not available for this account right now."
        return None

    def gift_card_redemption_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "block_gift_card_redemption"):
            return "Gift-card redemption is not available for this account."
        return None

    def gift_card_purchase_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "block_gift_card_purchase"):
            return "Gift-card purchases are not available for this account."
        return None

    def promotion_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "disable_promotions"):
            return "Promotional offers are not available for this account."
        return None

    def refund_allowed_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is not None and profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        if self.has_active_restriction(user, "block_refunds_no_supervisor"):
            return (
                "This customer's refunds require supervisor approval before processing."
            )
        return None

    # ── Workflow actions ───────────────────────────────────────
    def _record_action(
        self,
        user,
        action_type,
        *,
        actor_id,
        reason="",
        reason_category=None,
        notes="",
        evidence="",
        order_ids=None,
        payment_refs=None,
        before_risk=None,
        after_risk=None,
        before_account=None,
        after_account=None,
        approval_by=None,
    ):
        order_ids_json = json.dumps(list(order_ids or []), sort_keys=True)
        payment_refs_json = json.dumps(list(payment_refs or []), sort_keys=True)
        db.session.add(
            CustomerRiskAction(
                user_id=user.id,
                admin_id=actor_id,
                action_type=action_type,
                previous_risk_status=before_risk,
                new_risk_status=after_risk,
                previous_account_status=before_account,
                new_account_status=after_account,
                reason_category=reason_category,
                reason=(reason or "").strip(),
                notes=(notes or "").strip(),
                evidence=(evidence or "").strip(),
                order_ids=order_ids_json,
                payment_refs=payment_refs_json,
                ip_address=_client_ip(),
                approval_by=approval_by,
                approval_at=utcnow() if approval_by else None,
            )
        )
        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                action_type,
                "CustomerRiskProfile",
                user.id,
                before={
                    "risk_status": before_risk,
                    "account_status": before_account,
                },
                after={
                    "risk_status": after_risk,
                    "account_status": after_account,
                },
                ip_address=_client_ip() or None,
                change_summary=(reason or action_type).strip()[:500],
            )
        except Exception:
            pass

    def flag(
        self,
        user,
        *,
        actor_id,
        reason_category,
        reason,
        notes="",
        evidence="",
        order_ids=None,
        payment_refs=None,
    ):
        if reason_category not in FLAG_REASONS:
            raise ValidationError("Choose a valid flag reason.")
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to flag a customer.")
        profile = self.get_profile(user)
        before_risk, before_account = profile.risk_status, profile.account_status
        profile.risk_status = "flagged"
        if profile.account_status == "active":
            profile.account_status = "restricted"
        self._record_action(
            user,
            "flagged",
            actor_id=actor_id,
            reason=reason,
            reason_category=reason_category,
            notes=notes,
            evidence=evidence,
            order_ids=order_ids,
            payment_refs=payment_refs,
            before_risk=before_risk,
            after_risk=profile.risk_status,
            before_account=before_account,
            after_account=profile.account_status,
        )
        return profile

    def start_review(self, user, *, actor_id, case_owner_id=None, notes=""):
        profile = self.get_profile(user)
        before = profile.risk_status
        profile.risk_status = "under_review"
        if case_owner_id:
            profile.case_owner_id = case_owner_id
        profile.last_reviewed_at = utcnow()
        profile.last_reviewed_by = actor_id
        self._record_action(
            user,
            "under_review",
            actor_id=actor_id,
            reason="Review started",
            notes=notes,
            before_risk=before,
            after_risk=profile.risk_status,
            before_account=profile.account_status,
            after_account=profile.account_status,
        )
        return profile

    def keep_monitoring(self, user, *, actor_id, notes=""):
        profile = self.get_profile(user)
        before = profile.risk_status
        if profile.risk_status not in {"flagged", "under_review", "confirmed_fraud"}:
            profile.risk_status = "under_review"
        profile.last_reviewed_at = utcnow()
        profile.last_reviewed_by = actor_id
        self._record_action(
            user,
            "kept_monitoring",
            actor_id=actor_id,
            reason="Kept under monitoring",
            notes=notes,
            before_risk=before,
            after_risk=profile.risk_status,
            before_account=profile.account_status,
            after_account=profile.account_status,
        )
        return profile

    def clear_case(self, user, *, actor_id, notes=""):
        profile = self.get_profile(user)
        if not notes.strip():
            raise ValidationError("A review note is required before closing a case.")
        before = profile.risk_status
        profile.risk_status = "normal"
        profile.last_reviewed_at = utcnow()
        profile.last_reviewed_by = actor_id
        self._record_action(
            user,
            "case_cleared",
            actor_id=actor_id,
            reason="Case cleared",
            notes=notes,
            before_risk=before,
            after_risk=profile.risk_status,
            before_account=profile.account_status,
            after_account=profile.account_status,
        )
        return profile

    def escalate(self, user, *, actor_id, notes=""):
        profile = self.get_profile(user)
        before = profile.risk_status
        if profile.risk_status != "under_review":
            profile.risk_status = "under_review"
        self._record_action(
            user,
            "escalated",
            actor_id=actor_id,
            reason="Escalated for supervisor review",
            notes=notes,
            before_risk=before,
            after_risk=profile.risk_status,
            before_account=profile.account_status,
            after_account=profile.account_status,
        )
        return profile

    def add_restriction(
        self,
        user,
        *,
        restriction_type,
        reason,
        duration_days=None,
        actor_id=None,
        notes="",
    ):
        if restriction_type not in CUSTOMER_RESTRICTION_TYPES:
            raise ValidationError("Choose a valid restriction type.")
        if not reason or not reason.strip():
            raise ValidationError("A reason is required for a restriction.")
        existing = self.active_restriction_map(user).get(restriction_type)
        if existing is not None:
            raise ValidationError(
                "An active restriction of this type already exists for this customer."
            )
        expires_at = (
            utcnow() + timedelta(days=int(duration_days))
            if duration_days
            else None
        )
        restriction = CustomerRestriction(
            user_id=user.id,
            restriction_type=restriction_type,
            reason=reason.strip(),
            created_by=actor_id,
            expires_at=expires_at,
        )
        db.session.add(restriction)
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status == "active":
            profile.account_status = "restricted"
        self._record_action(
            user,
            "restricted",
            actor_id=actor_id,
            reason=f"{restriction_type}: {reason.strip()}",
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return restriction

    def lift_restriction(
        self, user, restriction_id, *, actor_id, reason=""
    ):
        restriction = CustomerRestriction.query.filter_by(
            id=restriction_id, user_id=user.id, is_active=True
        ).first()
        if restriction is None:
            raise ValidationError("That restriction is not active.")
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to lift a restriction.")
        restriction.is_active = False
        restriction.lifted_by = actor_id
        restriction.lifted_at = utcnow()
        restriction.lifted_reason = reason.strip()
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status == "restricted" and not self.active_restrictions(
            user
        ):
            profile.account_status = "active"
        self._record_action(
            user,
            "unrestricted",
            actor_id=actor_id,
            reason=f"Lifted {restriction.restriction_type}: {reason.strip()}",
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return restriction

    def suspend(self, user, *, actor_id, reason, duration_days=None, notes=""):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to suspend an account.")
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            raise ValidationError(
                "This account is already suspended, deleted, or anonymized."
            )
        profile.account_status = "suspended"
        profile.suspended_at = utcnow()
        profile.suspended_by = actor_id
        profile.suspension_reason = reason.strip()
        profile.suspended_until = (
            utcnow() + timedelta(days=int(duration_days))
            if duration_days
            else None
        )
        profile.session_revoked_at = utcnow()
        self._record_action(
            user,
            "suspended",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return profile

    def block(self, user, *, actor_id, reason, notes=""):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to block an account.")
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            raise ValidationError(
                "This account is already suspended, deleted, or anonymized."
            )
        profile.account_status = "blocked"
        profile.blocked_at = utcnow()
        profile.blocked_by = actor_id
        profile.block_reason = reason.strip()
        profile.session_revoked_at = utcnow()
        self._record_action(
            user,
            "blocked",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return profile

    def confirm_fraud(
        self,
        user,
        *,
        actor_id,
        reason,
        notes="",
        evidence="",
        order_ids=None,
        payment_refs=None,
        approval_by=None,
    ):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to confirm fraud.")
        profile = self.get_profile(user)
        before = profile.risk_status
        profile.risk_status = "confirmed_fraud"
        profile.fraud_confirmed_at = utcnow()
        profile.fraud_confirmed_by = actor_id
        self._record_action(
            user,
            "fraud_confirmed",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            evidence=evidence,
            order_ids=order_ids,
            payment_refs=payment_refs,
            before_risk=before,
            after_risk=profile.risk_status,
            before_account=profile.account_status,
            after_account=profile.account_status,
            approval_by=approval_by or actor_id,
        )
        return profile

    def soft_delete(
        self,
        user,
        *,
        actor_id,
        reason,
        notes="",
        confirm="",
    ):
        if confirm != "DELETE CUSTOMER":
            raise ValidationError('Type DELETE CUSTOMER to confirm soft deletion.')
        if not reason or not reason.strip():
            raise ValidationError("A deletion reason is required.")
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status in {"soft_deleted", "anonymized", "permanently_deleted"}:
            raise ValidationError("This account is already deleted or anonymized.")
        user.is_active = False
        profile.account_status = "soft_deleted"
        profile.deleted_at = utcnow()
        profile.deleted_by = actor_id
        profile.deletion_reason = reason.strip()
        profile.session_revoked_at = utcnow()
        self._record_action(
            user,
            "soft_deleted",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return profile

    def restore(self, user, *, actor_id, reason, notes=""):
        if not reason or not reason.strip():
            raise ValidationError("A restoration reason is required.")
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status == "active":
            raise ValidationError("This account is already active.")
        if profile.account_status in {"anonymized", "permanently_deleted"}:
            raise ValidationError(
                "Anonymized or permanently deleted accounts cannot be restored."
            )
        user.is_active = True
        profile.account_status = "active"
        profile.session_revoked_at = utcnow()
        # Lift only temporary restrictions; permanent ones need explicit review.
        now = utcnow()
        for restriction in CustomerRestriction.query.filter_by(
            user_id=user.id, is_active=True
        ):
            if restriction.expires_at is not None and restriction.expires_at > now:
                restriction.is_active = False
                restriction.lifted_by = actor_id
                restriction.lifted_at = now
                restriction.lifted_reason = (
                    "Auto-lifted on account restoration: " + reason.strip()
                )
        self._record_action(
            user,
            "restored",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
        )
        return profile

    def anonymize(
        self,
        user,
        *,
        actor_id,
        reason,
        notes="",
        approval_by=None,
    ):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to anonymize a customer.")
        profile = self.get_profile(user)
        before = profile.account_status
        if profile.account_status in {"anonymized", "permanently_deleted"}:
            raise ValidationError("This account is already anonymized or deleted.")
        original_email = user.email
        user.name = "Deleted Customer"
        user.email = _anonymized_email(user.id, original_email)
        user.phone = None
        user.birthday = None
        user.avatar = "default.png"
        if user.staff_address:
            user.staff_address = None
        self._clear_personal_records(user)
        user.is_active = False
        profile.account_status = "anonymized"
        profile.anonymized_at = utcnow()
        profile.anonymized_by = actor_id
        profile.session_revoked_at = utcnow()
        self._record_action(
            user,
            "anonymized",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
            approval_by=approval_by or actor_id,
        )
        return profile

    def delete_permanently(
        self,
        user,
        *,
        actor_id,
        reason,
        notes="",
        confirm="",
        approval_by=None,
    ):
        if confirm != "DELETE CUSTOMER":
            raise ValidationError("Type DELETE CUSTOMER to confirm permanent deletion.")
        if not reason or not reason.strip():
            raise ValidationError("A deletion reason is required.")
        blockers = self.permanent_deletion_blockers(user)
        if blockers:
            raise ValidationError(
                "This customer cannot be permanently deleted until the following "
                "items are resolved: " + "; ".join(blockers)
            )
        profile = self.get_profile(user)
        before = profile.account_status
        original_email = user.email
        user.name = "Deleted Customer"
        user.email = _anonymized_email(user.id, original_email)
        user.phone = None
        user.birthday = None
        user.is_active = False
        self._clear_personal_records(user)
        profile.account_status = "permanently_deleted"
        profile.deleted_at = utcnow()
        profile.deleted_by = actor_id
        profile.deletion_reason = reason.strip()
        profile.anonymized_at = utcnow()
        profile.anonymized_by = actor_id
        profile.session_revoked_at = utcnow()
        self._record_action(
            user,
            "permanently_deleted",
            actor_id=actor_id,
            reason=reason,
            notes=notes,
            before_risk=profile.risk_status,
            after_risk=profile.risk_status,
            before_account=before,
            after_account=profile.account_status,
            approval_by=approval_by or actor_id,
        )
        return profile

    # ── Deletion eligibility ───────────────────────────────────
    def permanent_deletion_blockers(self, user):
        blockers = []
        active_orders = Order.query.filter(
            Order.user_id == user.id,
            ~Order.status.in_(TERMINAL_ORDER_STATUSES),
        ).count()
        if active_orders:
            blockers.append(f"{active_orders} active order(s)")

        pending_payments = Order.query.filter(
            Order.user_id == user.id,
            Order.payment_status.in_(PENDING_PAYMENT_STATUSES),
        ).count()
        if pending_payments:
            blockers.append(f"{pending_payments} pending payment(s)")

        order_ids = [
            row[0]
            for row in Order.query.with_entities(Order.id)
            .filter(Order.user_id == user.id)
            .all()
        ]
        pending_refunds = (
            Refund.query.filter(
                Refund.order_id.in_(order_ids),
                Refund.status == "PENDING",
            ).count()
            if order_ids
            else 0
        )
        if pending_refunds:
            blockers.append(f"{pending_refunds} pending refund(s)")

        if order_ids:
            blockers.append(
                "order and invoice / tax records must be preserved"
            )

        active_gift_cards = GiftCard.query.filter(
            GiftCard.purchased_by_user_id == user.id,
            GiftCard.current_balance > 0,
            GiftCard.status.in_(("active", "partially_used")),
        ).count()
        if active_gift_cards:
            blockers.append(f"{active_gift_cards} active gift card(s)")

        if Decimal(str(user.wallet_balance or 0)) > 0:
            blockers.append("store-credit balance")

        if user.loyalty_points > 0:
            blockers.append("loyalty balance")

        unresolved_fraud = FraudAlert.query.filter_by(
            user_id=user.id, is_resolved=False
        ).count()
        if unresolved_fraud:
            blockers.append(f"{unresolved_fraud} unresolved fraud alert(s)")

        open_subscriptions = Subscription.query.filter_by(
            user_id=user.id, is_active=True
        ).count()
        if open_subscriptions:
            blockers.append("active subscription(s)")

        return blockers

    # ── Personal-data cleanup (safe to delete on anonymize/delete) ──
    def _clear_personal_records(self, user):
        from models import Cart, Notification, SavedAddress, Wishlist

        for model in (Cart, Wishlist, SavedAddress, Notification):
            for row in model.query.filter_by(user_id=user.id).all():
                db.session.delete(row)
        for history in LoginHistory.query.filter_by(user_id=user.id).all():
            db.session.delete(history)
        for message in Message.query.filter(
            (Message.sender_id == user.id) | (Message.receiver_id == user.id)
        ).all():
            db.session.delete(message)

    # ── Fraud blocklist ─────────────────────────────────────────
    def blocklist_error(self, user):
        profile = self.get_profile(user, create=False)
        if profile is None:
            return None
        if profile.account_status in BLOCKED_ACCOUNT_STATUSES:
            return NEUTRAL_MESSAGE
        return None

    def add_blocklist(
        self,
        *,
        identifier_type,
        identifier_value,
        reason,
        case_user_id=None,
        actor_id=None,
        auto_approve=False,
    ):
        if identifier_type not in BLOCKLIST_IDENTIFIER_TYPES:
            raise ValidationError("Choose a valid identifier type.")
        if not reason or not reason.strip():
            raise ValidationError("A reason is required for a blocklist entry.")
        normalized = _normalize_blocklist_value(identifier_type, identifier_value)
        identifier_hash = _identifier_hash(identifier_type, normalized)

        existing = FraudBlocklistEntry.query.filter_by(
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
        ).first()
        if existing is not None:
            raise ValidationError("This identifier is already on the blocklist.")

        status = "approved" if auto_approve else "pending_review"
        entry = FraudBlocklistEntry(
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            reason=reason.strip(),
            case_user_id=case_user_id,
            created_by=actor_id,
            status=status,
        )
        db.session.add(entry)
        db.session.flush()

        matches = self.find_matching_users(identifier_type, normalized)
        entry.match_count = len(matches)
        for matched_user, matched_field in matches:
            self.flag(
                matched_user,
                actor_id=actor_id,
                reason_category="multiple_linked_fraudulent_accounts",
                reason=(
                    f"Account matches a blocked identifier ({matched_field}). "
                    "Referral flagged for human review."
                ),
                notes=reason.strip(),
                order_ids=None,
                payment_refs=None,
            )
            if not self.has_active_restriction(matched_user, "block_purchases"):
                self.add_restriction(
                    matched_user,
                    restriction_type="block_purchases",
                    reason=(
                        "Temporary restriction applied for matching a blocked "
                        "identifier; pending human review."
                    ),
                    duration_days=7,
                    actor_id=actor_id,
                )
        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                "blocklist_added",
                "FraudBlocklistEntry",
                entry.id,
                after={
                    "identifier_type": identifier_type,
                    "identifier_hash_prefix": identifier_hash[:12],
                    "status": status,
                    "match_count": len(matches),
                },
                ip_address=_client_ip() or None,
                change_summary=(reason or "blocklist_added").strip()[:500],
            )
        except Exception:
            pass
        return entry

    def find_matching_users(self, identifier_type, normalized_value):
        """Return ``(user, matched_field)`` pairs matching a blocked identifier.

        Uses exact, validated matches only - never family names, IPs, or
        device proximity. Matches are never acted on automatically beyond
        flagging for human review plus temporary restrictions.
        """
        matches = []
        if identifier_type == "mobile_hash":
            target = digits_only(normalized_value)
            for user in User.query.filter(
                User.role == "customer",
                User.is_active.is_(True),
                User.phone.isnot(None),
            ).all():
                if mobile_last_10(user.phone) == target[-10:]:
                    matches.append((user, "mobile"))
            return matches
        if identifier_type == "email_hash":
            target = (normalized_value or "").lower()
            for user in User.query.filter(
                User.role == "customer",
                User.is_active.is_(True),
            ).all():
                if (user.email or "").lower() == target:
                    matches.append((user, "email"))
            return matches
        return matches

    def review_blocklist(self, entry_id, *, status, review_notes, actor_id):
        if status not in BLOCKLIST_STATUSES:
            raise ValidationError("Choose a valid review status.")
        entry = db.session.get(FraudBlocklistEntry, entry_id)
        if entry is None:
            raise ValidationError("Blocklist entry not found.")
        entry.status = status
        entry.reviewed_by = actor_id
        entry.reviewed_at = utcnow()
        entry.review_notes = (review_notes or "").strip()
        return entry

    # ── Notifications (neutral wording only) ───────────────────
    def notify_customer(self, user, *, message=None, actor_id=None):
        text = (
            message or NEUTRAL_MESSAGE
        ).strip()
        from utils.notifications import notify

        notify(
            user.id,
            "Account Status Update",
            text,
            "account",
            "",
        )
        return text

    # ── Review context for admin UI ─────────────────────────────
    def review_context(self, user):
        profile = self.get_profile(user)
        restrictions = self.active_restrictions(user)
        order_ids = [
            row[0]
            for row in Order.query.with_entities(Order.id)
            .filter(Order.user_id == user.id)
            .all()
        ]
        pending_refunds = (
            Refund.query.filter(
                Refund.order_id.in_(order_ids),
                Refund.status == "PENDING",
            ).all()
            if order_ids
            else []
        )
        gift_card_balance = (
            db.session.query(db.func.coalesce(db.func.sum(GiftCard.current_balance), 0))
            .filter(
                GiftCard.purchased_by_user_id == user.id,
                GiftCard.status.in_(("active", "partially_used")),
            )
            .scalar()
            or Decimal("0")
        )
        recent_actions = (
            CustomerRiskAction.query.filter_by(user_id=user.id)
            .order_by(CustomerRiskAction.created_at.desc())
            .limit(20)
            .all()
        )
        unresolved_alerts = FraudAlert.query.filter_by(
            user_id=user.id, is_resolved=False
        ).count()
        return {
            "profile": profile,
            "restrictions": restrictions,
            "restriction_map": {r.restriction_type: r for r in restrictions},
            "pending_refunds": pending_refunds,
            "gift_card_balance": Decimal(str(gift_card_balance)).quantize(
                Decimal("0.01")
            ),
            "loyalty_balance": user.loyalty_points,
            "wallet_balance": Decimal(str(user.wallet_balance or 0)),
            "recent_actions": recent_actions,
            "unresolved_alerts": unresolved_alerts,
            "blockers": self.permanent_deletion_blockers(user),
            "login_blocked": self.login_blocked_message(user) is not None,
        }
