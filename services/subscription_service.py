from datetime import date, timedelta
from decimal import Decimal

from clock import utcnow
from exceptions import ValidationError
from models import (
    Notification,
    PaymentLink,
    ProductVariant,
    RawMaterial,
    RecurringSubscription,
    SubscriptionOrderLog,
    User,
    db,
)
from realtime.events import emit_new_order, emit_stock_updated
from utils import ADMIN_PORTAL_ROLES


class SubscriptionService:
    def ensure_schedule(self, subscription):
        from models import SubscriptionSchedule

        schedule = subscription.schedule
        if schedule is None:
            next_run_at = subscription.next_billing_at or subscription.start_date
            schedule = SubscriptionSchedule(
                subscription_id=subscription.id,
                next_run_at=next_run_at,
            )
            db.session.add(schedule)
        return schedule

    def pause(self, subscription, paused_until):
        subscription.paused_until = paused_until
        subscription.status = "paused"
        if hasattr(subscription, "is_active"):
            subscription.is_active = False
            self.ensure_schedule(subscription).skipped_until = paused_until
        return subscription

    def resume(self, subscription):
        subscription.paused_until = None
        subscription.status = "active"
        if hasattr(subscription, "is_active"):
            subscription.is_active = True
            self.ensure_schedule(subscription).status = "active"
        return subscription

    def create_due_orders(self, today=None):
        today = today or utcnow().date()
        due = (
            RecurringSubscription.query.filter(
                RecurringSubscription.status == "active",
                RecurringSubscription.next_scheduled_date <= today,
            )
            .order_by(RecurringSubscription.next_scheduled_date.asc())
            .all()
        )
        summary = {"success": 0, "failed": 0, "order_ids": [], "log_ids": []}
        for subscription in due:
            try:
                result = self.generate_order_for_subscription(subscription, today=today)
                summary["success"] += 1
                summary["order_ids"].append(result["order"].id)
                summary["log_ids"].append(result["log"].id)
            except Exception as exc:
                db.session.rollback()
                self._record_failure(
                    subscription,
                    exc,
                    today=today,
                    status=self._failure_status(exc),
                )
                db.session.commit()
                summary["failed"] += 1
        return summary

    def generate_order_for_subscription(self, subscription, *, today=None):
        from bootstrap import get_container

        today = today or utcnow().date()
        if subscription.normalized_status != "active":
            raise ValidationError("Subscription is not active.")
        if subscription.paused_until and subscription.paused_until >= today:
            raise ValidationError("Subscription is paused.")

        user = db.session.get(User, subscription.user_id)
        if user is None or not user.is_active:
            raise ValidationError("Customer account is unavailable.")

        order_service = get_container().order_service
        lines = []
        subtotal = Decimal("0")
        for item in subscription.items.all():
            variant = db.session.get(ProductVariant, item.variant_id)
            line = order_service.build_line_from_variant(variant, item.quantity)
            lines.append(line)
            subtotal += line.unit_price * line.quantity
        if not lines:
            raise ValidationError("Subscription has no items.")

        address = user.saved_addresses.filter_by(is_default=True).first()
        store_details = get_container().app.config.get("STORE_DETAILS") or {}
        if address:
            address_line1 = address.address_line1
            address_line2 = address.address_line2
            city = address.city
            pincode = address.pincode
            phone = address.phone
            latitude = address.latitude
            longitude = address.longitude
        else:
            address_line1 = store_details.get("address_line1", "")
            address_line2 = store_details.get("address_line2", "")
            city = store_details.get("city", "")
            pincode = store_details.get("pincode", "")
            phone = user.phone or store_details.get("phone_tel", "")
            latitude = None
            longitude = None

        creation = order_service.create_order(
            user_id=user.id,
            branch_id=subscription.branch_id
            or get_container().app.config.get("DEFAULT_BRANCH_ID"),
            lines=lines,
            subtotal=subtotal,
            total=subtotal,
            payment_method="PAYMENT_LINK",
            payment_status="PENDING",
            status="PLACED",
            channel="subscription",
            source="SUBSCRIPTION",
            fulfillment_type="DELIVERY",
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            pincode=pincode,
            phone=phone,
            delivery_latitude=latitude,
            delivery_longitude=longitude,
            delivery_slot=subscription.delivery_window or "Subscription delivery",
            delivery_date=today,
            special_note=subscription.notes,
            payment_reason="subscription_cycle",
        )
        order = creation.order
        payment_link = PaymentLink.create_pending(
            user_id=user.id,
            order_id=order.id,
            purpose="ORDER",
            title=f"Payment for subscription order #{order.order_number}",
            amount=order.total,
            payment_method="UPI",
            success_url=f"/orders/{order.id}",
            cancel_url="/subscriptions",
            notes=(
                "Recurring orders are generated as payment-pending until a "
                "tokenized recurring payment gateway is connected."
            ),
        )
        log = SubscriptionOrderLog(
            subscription_id=subscription.id,
            order_id=order.id,
            status="success",
            notes=f"Order generated. Manual payment link: {payment_link.token}",
        )
        db.session.add(log)
        subscription.next_scheduled_date = self.next_scheduled_date(subscription, today)
        self._notify_user(
            user.id,
            "Subscription order created",
            f"Order #{order.order_number} is ready. Please complete payment for this cycle.",
            link=f"/orders/{order.id}",
        )
        db.session.commit()

        try:
            emit_new_order(order)
            for variant_id in set(creation.stock_update_variant_ids):
                variant = db.session.get(ProductVariant, variant_id)
                if variant:
                    emit_stock_updated(variant, include_customer=True)
            for material_id in set(creation.stock_update_material_ids):
                material = db.session.get(RawMaterial, material_id)
                if material:
                    emit_stock_updated(material)
        except Exception:
            pass
        return {"order": order, "log": log, "payment_link": payment_link}

    def next_scheduled_date(self, subscription, from_date=None):
        base = self._as_date(from_date or subscription.next_scheduled_date)
        frequency = (subscription.frequency or "weekly").strip().lower()
        if frequency == "daily":
            return base + timedelta(days=1)
        if frequency == "monthly":
            return base + timedelta(days=30)
        if frequency == "custom":
            days = subscription.days_of_week_list
            if not days:
                return base + timedelta(days=7)
            for offset in range(1, 8):
                candidate = base + timedelta(days=offset)
                if candidate.weekday() in days:
                    return candidate
            return base + timedelta(days=7)
        return base + timedelta(days=7)

    def _record_failure(self, subscription, exc, *, today, status):
        notes = str(exc) or exc.__class__.__name__
        log = SubscriptionOrderLog(
            subscription_id=subscription.id,
            order_id=None,
            status=status,
            notes=notes,
        )
        db.session.add(log)
        subscription.next_scheduled_date = self.next_scheduled_date(subscription, today)
        self._notify_user(
            subscription.user_id,
            "Subscription order could not be created",
            f"This cycle was skipped: {notes}",
            link="/subscriptions",
        )
        self._notify_admins(
            "Subscription cycle failed",
            f"Subscription #{subscription.id} failed: {notes}",
            link="/admin/subscriptions",
        )
        return log

    def _failure_status(self, exc):
        message = str(exc).lower()
        if "stock" in message or "out of stock" in message:
            return "failed_insufficient_stock"
        if "payment" in message:
            return "failed_payment"
        return "failed_generation"

    def _notify_user(self, user_id, title, message, link=""):
        db.session.add(
            Notification(
                user_id=user_id,
                title=title,
                message=message,
                type="subscription",
                priority="normal",
                link=link,
            )
        )

    def _notify_admins(self, title, message, link=""):
        admins = User.query.filter(
            User.is_active == True,
            User.role.in_(ADMIN_PORTAL_ROLES),
        ).all()
        for admin in admins:
            db.session.add(
                Notification(
                    user_id=admin.id,
                    title=title,
                    message=message,
                    type="subscription",
                    priority="high",
                    link=link,
                )
            )

    def _as_date(self, value):
        if isinstance(value, date):
            return value
        return value.date()
