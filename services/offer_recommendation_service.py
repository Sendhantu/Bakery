from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func

from clock import utcnow
from models import Coupon, Message, Order, OrderItem, PricingRule, Product, Review, db


class OfferRecommendationService:
    """Prepares the data shape for future AI-generated pricing and coupon ideas."""

    def __init__(self, config=None):
        self.config = config or {}

    def build_pricing_ai_context(self, *, window_days=None):
        window_days = int(
            window_days
            or self.config.get("AI_OFFERS_LOOKBACK_DAYS")
            or 30
        )
        now = utcnow()
        window_start = now - timedelta(days=window_days)
        active_order_filters = (
            Order.status != "CANCELLED",
            Order.placed_at >= window_start,
        )

        revenue_expr = Order.total + func.coalesce(
            Order.gift_card_redemption_amount, 0
        )
        revenue = (
            db.session.query(func.coalesce(func.sum(revenue_expr), 0))
            .filter(*active_order_filters)
            .scalar()
            or Decimal("0")
        )
        order_count = Order.query.filter(*active_order_filters).count()
        customer_count = (
            db.session.query(func.count(func.distinct(Order.user_id)))
            .filter(*active_order_filters, Order.user_id.isnot(None))
            .scalar()
            or 0
        )
        active_product_count = Product.query.filter_by(is_active=True).count()
        active_coupon_count = Coupon.query.filter_by(is_active=True).count()
        active_rule_count = PricingRule.query.filter_by(is_active=True).count()
        review_count = Review.query.filter(Review.created_at >= window_start).count()
        message_count = Message.query.filter(Message.sent_at >= window_start).count()

        top_products = (
            db.session.query(
                OrderItem.product_name.label("name"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
                func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .filter(*active_order_filters)
            .group_by(OrderItem.product_name)
            .order_by(func.coalesce(func.sum(OrderItem.quantity), 0).desc())
            .limit(5)
            .all()
        )

        return {
            "enabled": bool(self.config.get("AI_OFFERS_ENABLED", False)),
            "provider": self.config.get("AI_OFFERS_PROVIDER") or "Not configured",
            "model": self.config.get("AI_OFFERS_MODEL") or "Not selected",
            "lookback_days": window_days,
            "horizon_days": int(self.config.get("AI_OFFERS_HORIZON_DAYS") or 7),
            "signal_cards": [
                ("Active products", active_product_count),
                ("Recent orders", order_count),
                ("Recent customers", customer_count),
                ("Recent revenue", f"₹{Decimal(str(revenue or 0)):.2f}"),
                ("Active coupons", active_coupon_count),
                ("Manual pricing rules", active_rule_count),
                ("Reviews", review_count),
                ("Support messages", message_count),
            ],
            "top_products": [
                {
                    "name": row.name or "Unknown product",
                    "units": int(row.units or 0),
                    "revenue": Decimal(str(row.revenue or 0)),
                }
                for row in top_products
            ],
            "planned_outputs": [
                "Demand-based coupon ideas by category, branch, and time window.",
                "Customer-segment offers for first-time, returning, and loyal customers.",
                "Bundle suggestions using frequently purchased products.",
                "Slow-moving or aging-stock discount recommendations.",
                "Offer guardrails that keep margin, GST, coupon limits, and admin approval in control.",
            ],
        }
