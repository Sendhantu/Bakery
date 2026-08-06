import json
import re
from datetime import timedelta
from decimal import Decimal

from flask import session as flask_session
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError

from clock import utcnow
from models import (
    Cart,
    Category,
    CustomerActivity,
    LoginHistory,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    SearchAnalytics,
    User,
    Wishlist,
    db,
)
from recommendation_engine import get_recommendation_engine
from .query_helpers import enrich_products


ADDON_CATEGORY_NAME = "Party Add-ons"
SEARCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "i",
    "in",
    "is",
    "me",
    "need",
    "of",
    "or",
    "please",
    "show",
    "the",
    "to",
    "want",
    "with",
}


class BakeryMCPContextService:
    """Curated read-only context tools for local AI assistant features.

    This intentionally exposes summaries instead of raw SQL or arbitrary files.
    """

    def __init__(self, config=None):
        self.config = config or {}

    def available_tools(self):
        return [
            "customer.profile_summary",
            "customer.recent_logins",
            "customer.recent_activity",
            "customer.recent_orders",
            "catalog.search_products",
            "catalog.checkout_addons",
        ]

    def record_customer_activity(
        self,
        *,
        user_id=None,
        event_type,
        product_id=None,
        query_text="",
        metadata=None,
        request_obj=None,
    ):
        event_type = (event_type or "").strip().lower()[:40]
        query_text = (query_text or "").strip()[:255]
        if not event_type:
            return None

        metadata_json = None
        if metadata:
            metadata_json = json.dumps(metadata, default=str, sort_keys=True)[:4000]

        session_id = None
        try:
            session_id = flask_session.get("_id") or flask_session.get("csrf_token")
        except RuntimeError:
            session_id = None

        activity = CustomerActivity(
            user_id=user_id,
            event_type=event_type,
            product_id=product_id,
            query_text=query_text or None,
            metadata_json=metadata_json,
            session_id=(session_id or "")[:120] or None,
            ip_address=(
                request_obj.headers.get("X-Forwarded-For", request_obj.remote_addr)
                if request_obj
                else None
            ),
            user_agent=(
                (request_obj.headers.get("User-Agent") or "")[:200]
                if request_obj
                else None
            ),
        )
        db.session.add(activity)
        return activity

    def record_search_results(self, query_text, products):
        query_text = (query_text or "").strip()[:255]
        if not query_text:
            return
        try:
            for product in products[:10]:
                row = SearchAnalytics.query.filter_by(
                    query_text=query_text,
                    product_id=product.id,
                ).first()
                if row:
                    row.hit_count = int(row.hit_count or 0) + 1
                    row.last_searched_at = utcnow()
                else:
                    db.session.add(
                        SearchAnalytics(
                            query_text=query_text,
                            product_id=product.id,
                            hit_count=1,
                        )
                    )
        except SQLAlchemyError:
            db.session.rollback()

    def compact_product(self, product):
        return {
            "id": product.id,
            "name": product.name,
            "category": product.category.name if product.category else "",
            "price": float(Decimal(str(product.current_price or product.base_price))),
            "base_price": float(Decimal(str(product.base_price or 0))),
            "rating": float(product.avg_rating or 0),
            "review_count": int(product.review_count or 0),
            "stock_status": product.stock_status,
            "total_stock": int(product.total_stock or 0),
            "eggless": bool(product.is_eggless),
            "description": product.description or "",
            "tags": product.occasion_tags or "",
            "default_variant_id": product.default_variant_id,
            "preorder_required": bool(getattr(product, "preorder_required", False)),
            "minimum_notice_hours": int(
                getattr(product, "minimum_notice_hours", 0) or 0
            ),
            "image": product.image_src,
        }

    def search_products(self, query_text="", user_id=None, limit=8):
        try:
            engine = get_recommendation_engine()
            engine.build(rebuild=True)
            products, message = engine.recommend(user_id, query_text or "", limit=limit)
        except SQLAlchemyError:
            db.session.rollback()
            products, message = [], ""
        if not products:
            products, message = self._catalog_fallback_search(query_text, limit=limit)
        enrich_products(products)
        self.record_search_results(query_text, products)
        return products, message

    def _query_tokens(self, query_text):
        return [
            token
            for token in re.findall(r"\b[a-z0-9]+\b", (query_text or "").lower())
            if token not in SEARCH_STOPWORDS
        ]

    def _text_matches_token(self, text, token):
        if token in text:
            return True
        if token.endswith("s") and len(token) > 3 and token[:-1] in text:
            return True
        if not token.endswith("s") and f"{token}s" in text:
            return True
        return False

    def _product_search_text(self, product):
        parts = [
            product.name,
            product.category.name if product.category else "",
            product.occasion_tags,
            product.description,
            product.ingredients,
        ]
        return " ".join(part.strip().lower() for part in parts if part)

    def _catalog_fallback_search(self, query_text="", limit=8):
        tokens = self._query_tokens(query_text)
        lowered = (query_text or "").lower()
        products = Product.query.filter(Product.is_active.is_(True)).all()
        if not products:
            return [], "I could not find active products right now."

        wants_eggless = "eggless" in tokens or "no egg" in lowered
        wants_cakes = bool({"cake", "cakes"}.intersection(tokens))
        if wants_eggless:
            eggless_products = [product for product in products if product.is_eggless]
            if eggless_products:
                products = eggless_products

        budget = self._parse_budget(lowered)
        wants_cheaper = bool(
            re.search(r"\b(cheap|cheaper|affordable|budget)\b", lowered)
        )
        wants_premium = bool(
            re.search(r"\b(expensive|premium|best|top)\b", lowered)
        )

        scored = []
        for product in products:
            text = self._product_search_text(product)
            category_name = (product.category.name if product.category else "").lower()
            score = Decimal("0")
            if wants_eggless and product.is_eggless:
                score += Decimal("3")
            if wants_cakes and "cake" in category_name:
                score += Decimal("3")
            if product.is_featured:
                score += Decimal("0.6")
            if int(product.total_stock or 0) > 0:
                score += Decimal("0.4")
            for token in tokens:
                if token in {"eggless", "egg", "no", "cheap", "cheaper", "affordable", "budget", "under", "below", "rs"}:
                    continue
                if self._text_matches_token(text, token):
                    score += Decimal("1")
            if budget and Decimal(str(product.base_price or 0)) > Decimal(str(budget)):
                score -= Decimal("5")
            scored.append((score, product))

        def price_of(item):
            return Decimal(str(item[1].base_price or 0))

        scored.sort(
            key=lambda item: (
                item[0],
                bool(item[1].is_featured),
                price_of(item) * Decimal("-1"),
            ),
            reverse=True,
        )
        if wants_cheaper or budget:
            scored.sort(
                key=lambda item: (
                    item[0],
                    price_of(item) * Decimal("-1"),
                ),
                reverse=True,
            )
        if wants_premium:
            scored.sort(
                key=lambda item: (
                    item[0],
                    price_of(item),
                ),
                reverse=True,
            )
        results = [product for score, product in scored if score > 0][:limit]
        if not results:
            results = [product for _score, product in scored[:limit]]

        if results:
            names = ", ".join(product.name for product in results[:3])
            return results, f"I found these matches for you: {names}."
        return [], "No matching products are available right now."

    def _parse_budget(self, lowered):
        match = re.search(
            r"(?:under|below|less than|within|upto|up to|max|around)\s*(?:rs\.?|inr)?\s*([0-9][0-9,]*)(?:\.00)?",
            lowered,
        )
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    def get_checkout_addons(self, cart_items=None, limit=6):
        cart_product_ids = {
            int(item.product_id)
            for item in (cart_items or [])
            if getattr(item, "product_id", None)
        }
        query = Product.query.join(Category, Product.category_id == Category.id).filter(
            Product.is_active.is_(True),
            or_(
                Category.name == ADDON_CATEGORY_NAME,
                Product.occasion_tags.ilike("%addon%"),
            ),
        )
        if cart_product_ids:
            query = query.filter(~Product.id.in_(cart_product_ids))
        products = query.order_by(Product.is_featured.desc(), Product.base_price.asc()).limit(
            limit
        ).all()
        enrich_products(products)
        return products

    def _popular_products(self, limit=6):
        rows = (
            db.session.query(
                OrderItem.product_id,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.status != "CANCELLED", OrderItem.product_id.isnot(None))
            .group_by(OrderItem.product_id)
            .order_by(func.coalesce(func.sum(OrderItem.quantity), 0).desc())
            .limit(limit)
            .all()
        )
        product_ids = [row.product_id for row in rows]
        products = []
        if product_ids:
            unsorted = Product.query.filter(Product.id.in_(product_ids)).all()
            products = sorted(unsorted, key=lambda product: product_ids.index(product.id))
        if len(products) < limit:
            products.extend(
                Product.query.filter(
                    Product.is_active.is_(True),
                    ~Product.id.in_([product.id for product in products] or [0]),
                )
                .order_by(Product.is_featured.desc(), Product.created_at.desc())
                .limit(limit - len(products))
                .all()
            )
        enrich_products(products)
        return products

    def build_customer_context(self, user_id=None, query_text="", limit=None, history=None):
        limit = int(limit or self.config.get("AI_CONTEXT_PRODUCT_LIMIT") or 8)
        window_days = int(self.config.get("AI_CONTEXT_WINDOW_DAYS") or 90)
        window_start = utcnow() - timedelta(days=window_days)

        user = db.session.get(User, user_id) if user_id else None
        candidate_products, recommendation_message = self.search_products(
            query_text,
            user_id=user_id,
            limit=limit,
        )
        addon_products = self.get_checkout_addons(
            Cart.query.filter_by(user_id=user_id).all() if user_id else [],
            limit=4,
        )

        recent_logins = []
        recent_activity = []
        recent_orders = []
        cart_items = []
        wishlist_items = []

        if user_id:
            recent_logins = (
                LoginHistory.query.filter_by(user_id=user_id)
                .order_by(LoginHistory.login_time.desc())
                .limit(5)
                .all()
            )
            recent_activity = (
                CustomerActivity.query.filter(
                    CustomerActivity.user_id == user_id,
                    CustomerActivity.created_at >= window_start,
                )
                .order_by(CustomerActivity.created_at.desc())
                .limit(12)
                .all()
            )
            recent_orders = (
                Order.query.filter_by(user_id=user_id)
                .order_by(Order.placed_at.desc())
                .limit(5)
                .all()
            )
            cart_items = Cart.query.filter_by(user_id=user_id).all()
            wishlist_items = (
                Wishlist.query.filter_by(user_id=user_id)
                .order_by(Wishlist.added_at.desc())
                .limit(8)
                .all()
            )

        return {
            "tools": self.available_tools(),
            "customer": {
                "id": user.id if user else None,
                "name": user.name if user else "Guest",
                "role": user.role if user else "guest",
                "loyalty_points": user.loyalty_points if user else 0,
                "last_seen_at": user.last_seen_at.isoformat() if user and user.last_seen_at else None,
            },
            "conversation": [
                {
                    "role": turn.get("role"),
                    "content": (turn.get("content") or "")[:300],
                }
                for turn in (history or [])[-10:]
                if turn.get("role") in {"user", "assistant"} and turn.get("content")
            ],
            "recent_logins": [
                {
                    "status": login.status,
                    "at": login.login_time.isoformat() if login.login_time else None,
                }
                for login in recent_logins
            ],
            "recent_activity": [
                {
                    "event": activity.event_type,
                    "product": activity.product.name if activity.product else None,
                    "query": activity.query_text,
                    "at": activity.created_at.isoformat() if activity.created_at else None,
                }
                for activity in recent_activity
            ],
            "recent_orders": [
                {
                    "order_number": order.order_number,
                    "status": order.status,
                    "payment_status": order.payment_status,
                    "total": float(Decimal(str(order.total or 0))),
                    "placed_at": order.placed_at.isoformat() if order.placed_at else None,
                    "items": [
                        item.product_name
                        for item in order.items.order_by(OrderItem.id.asc()).limit(5)
                    ],
                }
                for order in recent_orders
            ],
            "cart": [
                {
                    "product": item.product.name if item.product else "",
                    "quantity": int(item.quantity or 0),
                }
                for item in cart_items
            ],
            "wishlist": [
                item.product.name
                for item in wishlist_items
                if item.product is not None
            ],
            "product_candidates": [
                self.compact_product(product) for product in candidate_products
            ],
            "popular_products": [
                self.compact_product(product) for product in self._popular_products(limit=limit)
            ],
            "checkout_addons": [
                self.compact_product(product) for product in addon_products
            ],
            "recommendation_message": recommendation_message,
        }

    def safe_build_customer_context(self, *args, **kwargs):
        try:
            return self.build_customer_context(*args, **kwargs)
        except SQLAlchemyError:
            db.session.rollback()
            return {
                "tools": self.available_tools(),
                "customer": {"id": None, "name": "Guest", "role": "guest"},
                "conversation": [
                    {
                        "role": turn.get("role"),
                        "content": (turn.get("content") or "")[:300],
                    }
                    for turn in (kwargs.get("history") or [])[-10:]
                    if turn.get("role") in {"user", "assistant"} and turn.get("content")
                ],
                "recent_logins": [],
                "recent_activity": [],
                "recent_orders": [],
                "cart": [],
                "wishlist": [],
                "product_candidates": [],
                "popular_products": [],
                "checkout_addons": [],
                "recommendation_message": "I can still help you browse our catalog.",
            }
