import json
import secrets
from decimal import Decimal, InvalidOperation

from flask import has_request_context, request, session

from clock import utcnow
from exceptions import ValidationError
from models import ConversionEvent, CustomerActivity, CustomerConsent, Order, db


CONSENT_CATEGORIES = {"necessary", "analytics", "marketing", "personalization"}
CONSENT_STATUSES = {"granted", "declined", "withdrawn"}
ANALYTICS_EVENTS = {
    "page_view",
    "view_item_list",
    "select_item",
    "view_item",
    "search",
    "add_to_cart",
    "remove_from_cart",
    "view_cart",
    "begin_checkout",
    "add_shipping_info",
    "add_payment_info",
    "purchase",
    "refund",
    "generate_lead",
    "sign_up",
    "login",
    "view_promotion",
    "select_promotion",
    "check_delivery_location",
    "delivery_location_serviceable",
    "delivery_location_blocked",
    "select_store_pickup",
    "open_ai_assistant",
    "ai_product_recommendation",
    "ai_add_to_cart",
    "subscription_started",
    "subscription_paused",
    "corporate_inquiry_submitted",
    "gift_card_purchased",
    "occasion_reminder_enabled",
    "qr_menu_opened",
    "qr_scanned",
    "dine_in_order_started",
    "dine_in_order_completed",
}
SAFE_METADATA_KEYS = {
    "category",
    "variant",
    "quantity",
    "coupon",
    "discount",
    "cart_value",
    "tax",
    "delivery_fee",
    "currency",
    "fulfillment_type",
    "table_label",
    "dining_area",
    "branch_id",
    "source",
}


def _session_id():
    if not has_request_context():
        return None
    if not session.get("analytics_session_id"):
        session["analytics_session_id"] = secrets.token_urlsafe(24)
    return session["analytics_session_id"]


def _client_ip():
    if not has_request_context():
        return None
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr


def _user_agent():
    if not has_request_context():
        return None
    return (request.headers.get("User-Agent") or "")[:200]


def _decimal_amount(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


class ConversionService:
    def __init__(self, config):
        self.config = config

    def record_consent(self, *, user_id=None, category="analytics", status="declined", source="web"):
        category = (category or "").strip().lower()
        status = (status or "").strip().lower()
        if category not in CONSENT_CATEGORIES:
            raise ValidationError("Unsupported consent category.")
        if status not in CONSENT_STATUSES:
            raise ValidationError("Unsupported consent status.")
        consent = CustomerConsent(
            user_id=user_id,
            session_id=_session_id(),
            category=category,
            status=status,
            source=(source or "web")[:40],
            ip_address=_client_ip(),
            user_agent=_user_agent(),
        )
        db.session.add(consent)
        if has_request_context():
            current = dict(session.get("consent_state") or {})
            current[category] = status
            session["consent_state"] = current
            session.modified = True
        return consent

    def has_consent(self, category="analytics", *, user_id=None):
        category = (category or "").strip().lower()
        if category == "necessary":
            return True
        if has_request_context():
            state = session.get("consent_state") or {}
            if state.get(category) in {"granted", "declined", "withdrawn"}:
                return state.get(category) == "granted"
        query = CustomerConsent.query.filter_by(category=category)
        if user_id:
            query = query.filter_by(user_id=user_id)
        else:
            query = query.filter_by(session_id=_session_id())
        latest = query.order_by(CustomerConsent.created_at.desc()).first()
        return bool(latest and latest.status == "granted")

    def sanitize_metadata(self, metadata):
        if not isinstance(metadata, dict):
            return {}
        sanitized = {}
        for key, value in metadata.items():
            key = str(key).strip()
            if key not in SAFE_METADATA_KEYS:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                sanitized[key] = str(value)[:160] if isinstance(value, str) else value
        return sanitized

    def record_event(self, event_name, *, user_id=None, consent_required=True, **payload):
        event_name = (event_name or "").strip().lower()
        if event_name not in ANALYTICS_EVENTS:
            raise ValidationError("Unsupported analytics event.")
        if consent_required and not self.has_consent("analytics", user_id=user_id):
            return None

        event_id = (payload.get("event_id") or "").strip()[:80] or secrets.token_urlsafe(24)
        if ConversionEvent.query.filter_by(event_id=event_id).first():
            return None
        metadata = self.sanitize_metadata(payload.get("metadata") or {})
        conversion = ConversionEvent(
            event_id=event_id,
            user_id=user_id,
            session_id=_session_id(),
            event_name=event_name,
            path=(payload.get("path") or (request.path if has_request_context() else "") or "")[:255],
            source=(payload.get("source") or "")[:80],
            medium=(payload.get("medium") or "")[:80],
            campaign=(payload.get("campaign") or "")[:120],
            content=(payload.get("content") or "")[:120],
            term=(payload.get("term") or "")[:120],
            product_id=payload.get("product_id"),
            order_id=payload.get("order_id"),
            table_id=payload.get("table_id"),
            branch_id=payload.get("branch_id"),
            amount=_decimal_amount(payload.get("amount")),
            currency=(payload.get("currency") or "INR")[:3],
            metadata_json=json.dumps(metadata, sort_keys=True),
        )
        db.session.add(conversion)
        db.session.add(
            CustomerActivity(
                user_id=user_id,
                event_type=event_name[:40],
                product_id=payload.get("product_id"),
                metadata_json=json.dumps(metadata, sort_keys=True),
                session_id=_session_id(),
                ip_address=_client_ip(),
                user_agent=_user_agent(),
            )
        )
        return conversion

    def record_purchase_once(self, order, *, event_id=None):
        stable_id = event_id or f"purchase-order-{order.id}"
        existing = ConversionEvent.query.filter_by(event_id=stable_id).first()
        if existing:
            return None
        return self.record_event(
            "purchase",
            user_id=order.user_id,
            consent_required=False,
            event_id=stable_id,
            order_id=order.id,
            branch_id=order.branch_id,
            table_id=getattr(order, "dining_table_id", None),
            amount=order.total,
            metadata={
                "tax": str(order.gst_amount or 0),
                "delivery_fee": str(order.delivery_charge or 0),
                "currency": "INR",
                "fulfillment_type": order.fulfillment_type,
            },
        )
