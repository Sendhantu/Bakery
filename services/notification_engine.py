import json
import re
from decimal import Decimal

from flask import has_request_context, url_for

from clock import utcnow
from exceptions import ValidationError
from models import (
    KitchenAlert,
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
    NotificationTemplate,
    OrderStatusNotificationLog,
    User,
    db,
)


SAFE_TEMPLATE_VARIABLES = {
    "bakeryName",
    "customerFirstName",
    "orderNumber",
    "orderTotal",
    "taxAmount",
    "pickupTime",
    "deliveryTime",
    "branchName",
    "trackingLink",
    "supportNumber",
    "productSummary",
}
TRANSACTIONAL_EVENTS = {
    "order_placed",
    "payment_successful",
    "order_confirmed",
    "baking_started",
    "decorating_started",
    "ready_for_pickup",
    "ready_for_dispatch",
    "out_for_delivery",
    "delivered",
    "delayed",
    "cancelled",
    "refund_initiated",
    "refund_completed",
    "subscription_order_created",
    "subscription_payment_failed",
    "corporate_quote_sent",
    "gift_card_issued",
}
EVENT_STATUS_MAP = {
    "PLACED": "order_placed",
    "CONFIRMED": "order_confirmed",
    "BAKING": "baking_started",
    "DECORATING": "decorating_started",
    "PREPARING": "baking_started",
    "READY_FOR_PICKUP": "ready_for_pickup",
    "READY_FOR_DISPATCH": "ready_for_dispatch",
    "OUT_FOR_DELIVERY": "out_for_delivery",
    "DELIVERED": "delivered",
    "DELAYED": "delayed",
    "CANCELLED": "cancelled",
    "REFUND_INITIATED": "refund_initiated",
    "REFUNDED": "refund_completed",
}
DEFAULT_TEMPLATES = {
    "order_placed": "Thank you for ordering from {{bakeryName}}! Your order {{orderNumber}} total is {{orderTotal}}, including applicable tax {{taxAmount}}. We are preparing your order.",
    "ready_for_pickup": "Your fresh order from {{bakeryName}} is ready for pickup. Please show order number {{orderNumber}} at the counter.",
    "delivered": "Your order {{orderNumber}} from {{bakeryName}} has been delivered. Thank you for ordering with us.",
    "delayed": "Your order {{orderNumber}} is delayed. We will keep you updated on the new promised time.",
}


def _mask_contact(value):
    value = (value or "").strip()
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:2]}***@{domain}" if domain else "***"
    digits = re.sub(r"\D+", "", value)
    if len(digits) >= 4:
        return f"***{digits[-4:]}"
    return "***" if value else ""


def _template_vars(body):
    return set(re.findall(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}", body or ""))


def _format_money(value):
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    return f"₹{amount}"


class NotificationEngine:
    def __init__(self, config, push_service=None):
        self.config = config
        self.push_service = push_service

    def validate_template(self, body):
        unknown = _template_vars(body) - SAFE_TEMPLATE_VARIABLES
        if unknown:
            raise ValidationError(
                "Unsupported template variables: " + ", ".join(sorted(unknown))
            )

    def get_or_create_preferences(self, user_id):
        prefs = NotificationPreference.query.filter_by(user_id=user_id).first()
        if prefs is None:
            prefs = NotificationPreference(user_id=user_id)
            db.session.add(prefs)
            db.session.flush()
        return prefs

    def upsert_template(
        self,
        *,
        event_type,
        channel,
        name,
        body,
        subject=None,
        provider_template_id=None,
        actor_id=None,
    ):
        event_type = (event_type or "").strip().lower()
        channel = (channel or "").strip().lower()
        self.validate_template(body)
        latest = (
            NotificationTemplate.query.filter_by(event_type=event_type, channel=channel)
            .order_by(NotificationTemplate.version.desc())
            .first()
        )
        version = int(latest.version or 0) + 1 if latest else 1
        if latest:
            latest.is_active = False
        template = NotificationTemplate(
            event_type=event_type,
            channel=channel,
            name=(name or event_type.replace("_", " ").title())[:120],
            subject=(subject or "")[:200],
            body=body,
            provider_template_id=(provider_template_id or "")[:120],
            version=version,
            transactional=event_type in TRANSACTIONAL_EVENTS,
            created_by=actor_id,
        )
        db.session.add(template)
        return template

    def template_for(self, event_type, channel):
        template = (
            NotificationTemplate.query.filter_by(
                event_type=event_type,
                channel=channel,
                is_active=True,
            )
            .order_by(NotificationTemplate.version.desc())
            .first()
        )
        if template:
            return template
        body = DEFAULT_TEMPLATES.get(
            event_type,
            "Your order {{orderNumber}} update from {{bakeryName}}: {{productSummary}}",
        )
        return NotificationTemplate(
            id=None,
            event_type=event_type,
            channel=channel,
            name="Default",
            subject="",
            body=body,
            version=1,
            transactional=True,
        )

    def render(self, template, variables):
        body = template.body or ""
        for key in SAFE_TEMPLATE_VARIABLES:
            body = re.sub(
                r"{{\s*" + re.escape(key) + r"\s*}}",
                str(variables.get(key, "")),
                body,
            )
        return body

    def order_variables(self, order):
        customer = order.customer
        branch = getattr(order, "branch", None)
        items = order.items.all() if hasattr(order.items, "all") else list(order.items)
        tracking_link = ""
        if order.tracking_token:
            if has_request_context():
                tracking_link = url_for(
                    "customer.track_order",
                    token=order.tracking_token,
                    _external=True,
                )
            else:
                root = (
                    self.config.get("CUSTOMER_PORTAL_URL")
                    or self.config.get("SITE_URL")
                    or "https://example.com"
                ).rstrip("/")
                tracking_link = f"{root}/track/{order.tracking_token}"
        return {
            "bakeryName": self.config.get("BAKERY_NAME", "SweetCrumbs Bakery"),
            "customerFirstName": (customer.name or "there").split()[0],
            "orderNumber": order.order_number,
            "orderTotal": _format_money(order.total),
            "taxAmount": _format_money(order.gst_amount),
            "pickupTime": order.delivery_slot or "",
            "deliveryTime": order.delivery_slot or "",
            "branchName": getattr(branch, "name", "") or self.config.get("STORE_DETAILS", {}).get("name", ""),
            "trackingLink": tracking_link,
            "supportNumber": self.config.get("STORE_DETAILS", {}).get("phone", ""),
            "productSummary": ", ".join(f"{item.quantity} x {item.product_name}" for item in items)[:300],
        }

    def channel_allowed(self, user_id, channel, *, transactional=True):
        if transactional:
            prefs = self.get_or_create_preferences(user_id)
            return bool(getattr(prefs, f"{channel}_transactional", True))
        prefs = self.get_or_create_preferences(user_id)
        return bool(getattr(prefs, f"marketing_{channel}", False))

    def enqueue(self, *, user_id, event_type, channel, message, order=None, template=None, recipient=""):
        idempotency_key = f"{getattr(order, 'id', 0) or user_id}:{event_type}:{channel}:{getattr(template, 'version', 1)}"
        existing = NotificationDeliveryLog.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False
        notification = None
        if channel == "in_app":
            order_link = ""
            if order:
                order_link = (
                    url_for("customer.order_detail", order_id=order.id)
                    if has_request_context()
                    else f"/orders/{order.id}"
                )
            notification = Notification(
                user_id=user_id,
                title=event_type.replace("_", " ").title(),
                message=message,
                type="order" if order else "system",
                channel="in_app",
                link=order_link,
            )
            db.session.add(notification)
            db.session.flush()
        log = NotificationDeliveryLog(
            notification_id=getattr(notification, "id", None),
            user_id=user_id,
            order_id=getattr(order, "id", None),
            event_type=event_type,
            channel=channel,
            recipient_masked=_mask_contact(recipient),
            template_id=getattr(template, "id", None),
            template_version=getattr(template, "version", 1),
            status="queued",
            provider="internal" if channel == "in_app" else channel,
            idempotency_key=idempotency_key,
        )
        db.session.add(log)
        return log, True

    def notify_order_event(self, order, event_type, *, channels=None):
        user = order.customer
        variables = self.order_variables(order)
        channels = channels or ("in_app", "email", "sms", "whatsapp")
        logs = []
        for channel in channels:
            if channel != "in_app" and not self.channel_allowed(user.id, channel, transactional=True):
                continue
            template = self.template_for(event_type, channel)
            message = self.render(template, variables)
            recipient = user.email if channel == "email" else user.phone
            if channel in {"email", "sms", "whatsapp"} and not recipient:
                continue
            log, created = self.enqueue(
                user_id=user.id,
                event_type=event_type,
                channel=channel,
                message=message,
                order=order,
                template=template,
                recipient=recipient,
            )
            if created:
                log.status = "sent" if channel == "in_app" else "queued"
                log.sent_at = utcnow() if channel == "in_app" else None
            logs.append(log)
        return logs

    def notify_order_status(self, order, status):
        event_type = EVENT_STATUS_MAP.get((status or "").strip().upper())
        if not event_type:
            return []
        logs = self.notify_order_event(order, event_type)
        for log in logs:
            if log.channel == "in_app":
                existing = OrderStatusNotificationLog.query.filter_by(
                    order_id=order.id,
                    status=status,
                    channel="in_app",
                ).first()
                if existing is None:
                    db.session.add(
                        OrderStatusNotificationLog(
                            order_id=order.id,
                            status=status,
                            channel="in_app",
                            template=event_type,
                            delivery_status="sent",
                        )
                    )
        return logs

    def create_kitchen_alert(self, order):
        existing = KitchenAlert.query.filter_by(order_id=order.id, alert_type="new_order").first()
        if existing:
            return existing, False
        payload = {
            "order_number": order.order_number,
            "fulfillment_type": order.fulfillment_type,
            "table": getattr(getattr(order, "dining_table", None), "display_name", ""),
            "delivery_slot": order.delivery_slot,
            "delivery_date": order.delivery_date.isoformat() if order.delivery_date else "",
            "payment_status": order.payment_status,
            "items": [
                {
                    "name": item.product_name,
                    "variant": item.variant_name,
                    "quantity": item.quantity,
                }
                for item in order.items.all()
            ],
            "special_note": order.special_note or "",
        }
        alert = KitchenAlert(
            order_id=order.id,
            branch_id=order.branch_id,
            priority="high" if order.is_suspicious else "normal",
            payload_json=json.dumps(payload, sort_keys=True),
        )
        db.session.add(alert)
        return alert, True
