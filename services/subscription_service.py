import json
from datetime import datetime, timedelta
from decimal import Decimal

from models import Order, OrderItem, Product, ProductVariant, Subscription, SubscriptionSchedule, User, db


class SubscriptionService:
    def ensure_schedule(self, subscription):
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
        subscription.status = "PAUSED"
        subscription.is_active = False
        self.ensure_schedule(subscription).skipped_until = paused_until
        return subscription

    def resume(self, subscription):
        subscription.paused_until = None
        subscription.status = "ACTIVE"
        subscription.is_active = True
        self.ensure_schedule(subscription).status = "active"
        return subscription

    def _subscription_items(self, subscription):
        if not subscription.items_json:
            return []
        try:
            return json.loads(subscription.items_json)
        except (TypeError, json.JSONDecodeError):
            return []

    def _copy_items_to_order(self, order, items, user):
        subtotal = Decimal("0")
        for entry in items:
            product = db.session.get(Product, entry.get("product_id"))
            if product is None:
                continue
            variant = None
            variant_id = entry.get("variant_id")
            if variant_id:
                variant = db.session.get(ProductVariant, variant_id)
            quantity = int(entry.get("quantity") or 1)
            price = Decimal(str(entry.get("unit_price") or product.base_price or 0))
            line_total = price * quantity
            subtotal += line_total
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    variant_id=variant.id if variant else None,
                    product_name=product.name,
                    variant_name=variant.name if variant else "",
                    quantity=quantity,
                    unit_price=price,
                    subtotal=line_total,
                )
            )
        discount_pct = Decimal(str(subscription.discount_pct or 0))
        discount = (subtotal * discount_pct / Decimal("100")).quantize(Decimal("0.01"))
        order.subtotal = subtotal
        order.discount = discount
        order.total = subtotal - discount
        if user:
            default_address = user.saved_addresses.filter_by(is_default=True).first()
            if default_address:
                order.address_line1 = default_address.address_line1
                order.address_line2 = default_address.address_line2
                order.city = default_address.city
                order.pincode = default_address.pincode
                order.phone = default_address.phone

    def create_due_orders(self, now=None):
        now = now or datetime.utcnow()
        schedules = (
            SubscriptionSchedule.query.join(Subscription)
            .filter(
                Subscription.is_active.is_(True),
                SubscriptionSchedule.status == "active",
                SubscriptionSchedule.next_run_at <= now,
            )
            .all()
        )
        created_orders = []
        for schedule in schedules:
            subscription = schedule.subscription
            if subscription.paused_until and subscription.paused_until > now:
                continue
            user = db.session.get(User, subscription.user_id)
            order = Order(
                order_number=Order.generate_order_number(),
                user_id=subscription.user_id,
                branch_id=subscription.branch_id,
                source="SUBSCRIPTION",
                status="PLACED",
                fulfillment_type="DELIVERY",
                payment_method="COD",
                payment_status="PENDING",
                delivery_window=subscription.delivery_window,
            )
            db.session.add(order)
            db.session.flush()
            items = self._subscription_items(subscription)
            if items:
                self._copy_items_to_order(order, items, user)
            else:
                order.total = subscription.price_paid or 0
                order.subtotal = order.total
            schedule.last_generated_at = now
            schedule.next_run_at = now + self._interval_for(subscription.recurrence)
            created_orders.append(order)
        if created_orders:
            db.session.commit()
        return created_orders

    def _interval_for(self, recurrence):
        recurrence = (recurrence or "monthly").strip().lower()
        if recurrence == "daily":
            return timedelta(days=1)
        if recurrence == "weekly":
            return timedelta(days=7)
        return timedelta(days=30)
