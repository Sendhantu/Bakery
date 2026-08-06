from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    abort,
    session,
)
from flask_login import login_required, current_user
from app import csrf
from bootstrap import get_container
from clock import utcnow
from exceptions import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from models import (
    db,
    Product,
    ProductVariant,
    Category,
    Cart,
    Wishlist,
    Order,
    OrderItem,
    Payment,
    Refund,
    User,
    Coupon,
    Subscription,
    Review,
    Message,
    Notification,
    AddressChange,
    ModificationRequest,
    PaymentLink,
    GiftCard,
    RecurringSubscription,
    SubscriptionItem,
    SubscriptionOrderLog,
    LoyaltyLedger,
    FraudAlert,
    RawMaterial,
    calculate_loyalty_redemption,
    get_loyalty_config,
    cache,
)
from recommendation_engine import get_recommendation_engine
from realtime.events import (
    emit_new_order,
    emit_order_cancelled,
    emit_order_refunded,
    emit_support_message,
    emit_stock_updated,
)
from services import (
    enrich_products,
    get_customer_orders_page,
    get_customer_products_page,
    get_customer_wishlist_page,
    page_args,
)
from utils import (
    ADMIN_PORTAL_ROLES,
    extract_address_payload,
    get_saved_addresses_for_user,
    get_selected_saved_address,
    has_role,
    save_address_for_customer,
    send_order_placed_email,
    send_order_sms,
    send_order_whatsapp,
    validate_address_payload,
)
from datetime import datetime, timedelta
from decimal import Decimal
import random, json, re

customer_bp = Blueprint("customer", __name__)


@customer_bp.before_request
def redirect_delivery_users_to_delivery_portal():
    if current_app.config.get("PORTAL_ROLE") != "customer":
        from routes.auth import portal_url_for_role

        if request.endpoint == "customer.home":
            return redirect(url_for("auth.login"))
        if current_user.is_authenticated and has_role(
            current_user, *ADMIN_PORTAL_ROLES
        ):
            return redirect(portal_url_for_role("admin", url_for("admin.dashboard")))
        if current_user.is_authenticated and has_role(current_user, "delivery"):
            return redirect(
                portal_url_for_role("delivery", url_for("delivery.dashboard"))
            )
        abort(404)

    if request.endpoint == "customer.ai_recommend":
        return None

    if current_user.is_authenticated and has_role(current_user, "delivery"):
        from routes.auth import portal_url_for_role

        return redirect(portal_url_for_role("delivery", url_for("delivery.dashboard")))
    if current_user.is_authenticated and has_role(current_user, *ADMIN_PORTAL_ROLES):
        from routes.auth import portal_url_for_role

        return redirect(portal_url_for_role("admin", url_for("admin.dashboard")))


def notify(user_id, title, message, ntype="order", link=""):
    db.session.add(
        Notification(
            user_id=user_id, title=title, message=message, type=ntype, link=link
        )
    )


SUPPORT_STAFF_ROLE_PRIORITY = {
    "admin": 0,
    "super_admin": 0,
    "branch_manager": 1,
    "cashier": 2,
    "kitchen_staff": 3,
}


def support_staff_members():
    staff = (
        User.query.filter(
            User.role.in_(ADMIN_PORTAL_ROLES),
            User.is_active.is_(True),
        )
        .order_by(User.name.asc())
        .all()
    )
    return sorted(
        staff,
        key=lambda user: (
            SUPPORT_STAFF_ROLE_PRIORITY.get((user.role or "").lower(), 99),
            user.name or "",
        ),
    )


def support_staff_ids():
    return [staff.id for staff in support_staff_members()]


def support_recipient():
    staff = support_staff_members()
    return staff[0] if staff else None


def customer_support_thread_filter(customer_id):
    staff_ids = support_staff_ids()
    if not staff_ids:
        return Message.id == -1
    return or_(
        (Message.sender_id == customer_id) & (Message.receiver_id.in_(staff_ids)),
        (Message.sender_id.in_(staff_ids)) & (Message.receiver_id == customer_id),
    )


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def can_use_customer_ai(user=None):
    user = user or current_user
    return bool(
        getattr(user, "is_authenticated", False)
        and has_role(user, "customer", *ADMIN_PORTAL_ROLES)
    )


def ai_surface_return_path(surface=None):
    surface = (surface or "").strip().lower()
    if surface == "shop":
        return url_for("customer.products", _anchor="ai-assistant")
    if surface == "support":
        return url_for("customer.chat", _anchor="ai-assistant")
    return url_for("customer.home", _anchor="ai-assistant")


def ai_auth_required_payload(surface=None, *, expired=False):
    next_url = ai_surface_return_path(surface)
    message = (
        "Your session has expired. Please log in again to use our AI bakery assistant."
        if expired
        else "Please log in to use our AI bakery assistant."
    )
    return {
        "ok": False,
        "code": "auth_required",
        "message": message,
        "login_url": url_for("auth.login", next=next_url),
        "register_url": url_for("auth.register", next=next_url),
    }


def build_order_detail_context(order):
    return {
        "order": order,
        "items": order.items.all(),
        "can_cancel": order.can_cancel(),
        "can_modify": order.can_modify(),
        "can_change_addr": order.can_change_address(),
        "pending_payment_link": PaymentLink.query.filter_by(
            user_id=order.user_id,
            order_id=order.id,
            purpose="ORDER",
            status="PENDING",
        )
        .order_by(PaymentLink.id.desc())
        .first(),
    }


def split_preparation_steps(text):
    if not text:
        return []

    steps = []
    for block in re.split(r"[\r\n]+", text):
        block = block.strip(" \t-•")
        if not block:
            continue
        for step in re.split(r"(?<=[.!?])\s+", block):
            step = step.strip(" \t-•")
            if step:
                steps.append(step)
    return steps


def validate_preorder_requirements(cart_items, scheduled_for):
    for item in cart_items:
        product = item.product
        if not product or not getattr(product, "preorder_required", False):
            continue

        minimum_notice_hours = max(
            1, int(getattr(product, "minimum_notice_hours", 24) or 24)
        )
        hours_until_fulfillment = (scheduled_for - utcnow()).total_seconds() / 3600
        if hours_until_fulfillment < minimum_notice_hours:
            raise ValueError(
                f"{product.name} requires at least {minimum_notice_hours} hours of preorder notice."
            )


def has_delivered_product_order(user_id, product_id):
    return (
        db.session.query(Order.id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            Order.user_id == user_id,
            Order.status == "DELIVERED",
            OrderItem.product_id == product_id,
        )
        .first()
        is not None
    )


def resolve_product_variant(product, variant_id=None):
    if variant_id:
        return ProductVariant.query.filter_by(
            id=variant_id,
            product_id=product.id,
        ).first()
    return product.variants.order_by(ProductVariant.id.asc()).first()


def serialize_cart_line(product, variant, quantity, cart_id=None, is_guest=False):
    price = get_container().pricing_service.resolve_product_price(product, variant)[
        "price"
    ]
    max_qty = (
        variant.stock
        if variant and variant.stock and variant.stock > 0
        else max(int(quantity or 1), 1)
    )
    remove_url = url_for("customer.remove_from_cart", cart_id=cart_id or 0)
    if is_guest:
        remove_url = url_for(
            "customer.remove_from_cart",
            cart_id=0,
            product_id=product.id,
            variant_id=variant.id if variant else None,
        )

    return {
        "cart_id": cart_id,
        "product_id": product.id,
        "variant_id": variant.id if variant else None,
        "product": product,
        "variant": variant,
        "quantity": int(quantity or 1),
        "price": price,
        "line_total": price * int(quantity or 1),
        "max_qty": int(max_qty or 1),
        "image": product.image_src,
        "is_guest": is_guest,
        "remove_url": remove_url,
    }


def serialize_ai_product_payload(product):
    variants = (
        ProductVariant.query.filter_by(product_id=product["id"])
        .order_by(ProductVariant.id.asc())
        .all()
    )
    return {
        "id": product["id"],
        "name": product["name"],
        "price": product["price"],
        "current_price": product["price"],
        "base_price": float(product.get("base_price") or product["price"]),
        "category": product.get("category", ""),
        "image": product.get("image", ""),
        "description": product.get("description", ""),
        "rating": float(product.get("rating") or 0),
        "review_count": int(product.get("review_count") or 0),
        "stock_status": product.get("stock_status", ""),
        "stock": int(product.get("total_stock") or 0),
        "eggless": bool(product.get("eggless", False)),
        "default_variant_id": product.get("default_variant_id"),
        "preorder_required": bool(product.get("preorder_required", False)),
        "minimum_notice_hours": int(product.get("minimum_notice_hours") or 0),
        "variants": [
            {
                "id": variant.id,
                "name": variant.name,
                "price": float(Decimal(str(variant.price or 0))),
                "stock": int(variant.stock or 0),
            }
            for variant in variants
        ],
        "detail_url": url_for("customer.product_detail", product_id=product["id"]),
    }


def apply_checkout_addons(user_id, form):
    addon_ids = []
    for value in form.getlist("checkout_addon_product_id"):
        try:
            addon_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not addon_ids:
        return []

    added = []
    for product_id in addon_ids:
        product = Product.query.filter_by(id=product_id, is_active=True).first()
        if not product:
            continue
        variant = resolve_product_variant(product)
        quantity = max(
            form.get(f"checkout_addon_quantity_{product_id}", 1, type=int) or 1,
            1,
        )
        if not variant or int(variant.stock or 0) < quantity:
            raise ValidationError(f"{product.name} is currently out of stock.")

        existing = Cart.query.filter_by(
            user_id=user_id,
            product_id=product.id,
            variant_id=variant.id,
        ).first()
        if existing:
            existing.quantity = min(
                existing.quantity + quantity,
                int(variant.stock or 0),
            )
        else:
            db.session.add(
                Cart(
                    user_id=user_id,
                    product_id=product.id,
                    variant_id=variant.id,
                    quantity=quantity,
                )
            )
        added.append(product)
    return added


def set_guest_cart(entries):
    if entries:
        session["guest_cart"] = entries
    else:
        session.pop("guest_cart", None)
    session.modified = True


def load_guest_cart_lines():
    raw_entries = session.get("guest_cart", [])
    normalized_entries = []
    lines = []
    changed = False

    for entry in raw_entries:
        try:
            product_id = int(entry.get("product_id") or 0)
            variant_id = int(entry.get("variant_id") or 0)
            quantity = max(1, int(entry.get("quantity") or 1))
        except (AttributeError, TypeError, ValueError):
            changed = True
            continue

        product = db.session.get(Product, product_id)
        if not product or not product.is_active:
            changed = True
            continue

        variant = resolve_product_variant(product, variant_id)
        if not variant:
            changed = True
            continue

        normalized_entry = {
            "product_id": product.id,
            "variant_id": variant.id,
            "quantity": quantity,
        }
        normalized_entries.append(normalized_entry)
        lines.append(serialize_cart_line(product, variant, quantity, is_guest=True))
        if normalized_entry != entry:
            changed = True

    if changed:
        set_guest_cart(normalized_entries)

    return lines


def get_cart_lines(user_id=None):
    if user_id is None and current_user.is_authenticated:
        user_id = current_user.id

    if user_id is None:
        return load_guest_cart_lines()

    items = Cart.query.filter_by(user_id=user_id).all()
    lines = []
    for item in items:
        if not item.product:
            continue
        variant = item.variant or resolve_product_variant(item.product, item.variant_id)
        lines.append(
            serialize_cart_line(
                product=item.product,
                variant=variant,
                quantity=item.quantity,
                cart_id=item.id,
                is_guest=False,
            )
        )
    return lines


def calculate_cart_totals(lines):
    subtotal = sum(
        (Decimal(str(line["price"])) * int(line["quantity"]) for line in lines),
        Decimal("0"),
    )
    total_quantity = sum(int(line["quantity"]) for line in lines)
    return subtotal, total_quantity


def compute_free_delivery_context(subtotal, has_items=True):
    """Return the free-delivery configuration and the current cart's progress toward it.

    Uses the same delivery configuration and subtotal that the existing delivery-charge
    calculation relies on, so the displayed message always matches the applied fee.
    """
    delivery_threshold = Decimal(
        str(current_app.config.get("DELIVERY_FREE_THRESHOLD", 500))
    )
    delivery_fee = Decimal(str(current_app.config.get("DELIVERY_CHARGE", 50)))

    if delivery_threshold <= 0:
        delivery_charge = Decimal("0")
        remaining = Decimal("0")
        progress = 100
    elif not has_items:
        delivery_charge = Decimal("0")
        remaining = Decimal("0")
        progress = 0
    elif subtotal >= delivery_threshold:
        delivery_charge = Decimal("0")
        remaining = Decimal("0")
        progress = 100
    else:
        delivery_charge = delivery_fee
        remaining = max(Decimal("0"), delivery_threshold - subtotal)
        progress = min(100, int((subtotal * 100) / delivery_threshold))

    return {
        "delivery_threshold": delivery_threshold,
        "delivery_fee": delivery_fee,
        "delivery_charge": delivery_charge,
        "free_delivery_unlocked": has_items and delivery_charge == Decimal("0"),
        "amount_to_free_delivery": remaining,
        "free_delivery_progress": progress,
    }


def upsert_guest_cart_item(product, variant, quantity):
    guest_cart = list(session.get("guest_cart", []))
    updated_quantity = quantity

    for entry in guest_cart:
        same_product = int(entry.get("product_id") or 0) == product.id
        same_variant = int(entry.get("variant_id") or 0) == variant.id
        if not (same_product and same_variant):
            continue

        updated_quantity = min(
            max(1, int(entry.get("quantity") or 1) + quantity),
            max(int(variant.stock or 0), 1),
        )
        entry["quantity"] = updated_quantity
        set_guest_cart(guest_cart)
        return serialize_cart_line(product, variant, updated_quantity, is_guest=True)

    updated_quantity = min(max(1, quantity), max(int(variant.stock or 0), 1))
    guest_cart.append(
        {
            "product_id": product.id,
            "variant_id": variant.id,
            "quantity": updated_quantity,
        }
    )
    set_guest_cart(guest_cart)
    return serialize_cart_line(product, variant, updated_quantity, is_guest=True)


def update_guest_cart_item(product_id, variant_id, quantity):
    guest_cart = []
    found = False

    for entry in session.get("guest_cart", []):
        same_product = int(entry.get("product_id") or 0) == product_id
        same_variant = int(entry.get("variant_id") or 0) == variant_id
        if not (same_product and same_variant):
            guest_cart.append(entry)
            continue

        found = True
        if quantity >= 1:
            product = db.session.get(Product, product_id)
            variant = resolve_product_variant(product, variant_id) if product else None
            available_stock = int(variant.stock or 0) if variant else quantity
            entry["quantity"] = min(quantity, max(available_stock, 1))
            guest_cart.append(entry)

    set_guest_cart(guest_cart)
    return found


def merge_guest_cart_into_user(user_id):
    guest_lines = load_guest_cart_lines()
    if not guest_lines:
        return 0

    merged_items = 0
    for line in guest_lines:
        variant = line["variant"]
        available_stock = int(variant.stock or 0) if variant else 0
        if available_stock <= 0:
            continue

        quantity = min(int(line["quantity"]), available_stock)
        existing = Cart.query.filter_by(
            user_id=user_id,
            product_id=line["product_id"],
            variant_id=line["variant_id"],
        ).first()
        if existing:
            existing.quantity = min(existing.quantity + quantity, available_stock)
        else:
            db.session.add(
                Cart(
                    user_id=user_id,
                    product_id=line["product_id"],
                    variant_id=line["variant_id"],
                    quantity=quantity,
                )
            )
        merged_items += quantity

    set_guest_cart([])
    return merged_items


def build_cart_summary(user_id=None, added_item=None):
    lines = get_cart_lines(user_id=user_id)
    subtotal, total_quantity = calculate_cart_totals(lines)
    checkout_url = url_for("customer.checkout")
    if user_id is None and not current_user.is_authenticated:
        checkout_url = url_for("auth.login", next=url_for("customer.checkout"))

    free_delivery = compute_free_delivery_context(subtotal, has_items=bool(lines))

    payload = {
        "count": total_quantity,
        "line_count": len(lines),
        "subtotal": float(subtotal),
        "delivery_threshold": float(free_delivery["delivery_threshold"]),
        "delivery_charge": float(free_delivery["delivery_charge"]),
        "amount_to_free_delivery": float(free_delivery["amount_to_free_delivery"]),
        "free_delivery_unlocked": free_delivery["free_delivery_unlocked"],
        "free_delivery_progress": free_delivery["free_delivery_progress"],
        "cart_url": url_for("customer.cart"),
        "checkout_url": checkout_url,
        "items": [
            {
                "name": line["product"].name,
                "variant": line["variant"].name if line["variant"] else "",
                "quantity": line["quantity"],
                "line_total": float(line["line_total"]),
                "image": line["image"],
            }
            for line in lines[:3]
        ],
    }

    if added_item:
        payload["added_item"] = {
            "name": added_item["product"].name,
            "variant": added_item["variant"].name if added_item["variant"] else "",
            "quantity": added_item["quantity"],
            "line_total": float(added_item["line_total"]),
            "image": added_item["image"],
        }

    return payload


def create_order_payment_link(order):
    return PaymentLink.create_pending(
        user_id=order.user_id,
        order_id=order.id,
        purpose="ORDER",
        title=f"Payment for Order #{order.order_number}",
        amount=order.total,
        payment_method=order.payment_method,
        success_url=url_for("customer.order_detail", order_id=order.id),
        cancel_url=url_for("customer.order_detail", order_id=order.id),
        notes="Gateway integration pending. Do not mark this payment as completed until the payment provider is connected.",
    )


def create_subscription_payment_link(plan, price, discount_pct, days):
    return PaymentLink.create_pending(
        user_id=current_user.id,
        purpose="SUBSCRIPTION",
        title=f"{plan.title()} Sweet Club Membership",
        amount=Decimal(str(price)),
        payment_method="CARD",
        subscription_plan=plan,
        subscription_discount_pct=Decimal(str(discount_pct)),
        subscription_duration_days=days,
        success_url=url_for("customer.subscription"),
        cancel_url=url_for("customer.subscription"),
        notes="Membership stays inactive until the payment gateway confirms a successful payment.",
    )


def send_gift_card_email(card, recipient_email):
    if not recipient_email:
        return
    try:
        from tasks.messaging import send_email

        html = render_template("customer/gift_card_email.html", card=card)
        text = (
            f"Your SweetCrumbs gift card code is {card.code}. "
            f"Balance: ₹{Decimal(str(card.current_balance or 0)):.2f}"
        )
        send_email.delay(recipient_email, "Your SweetCrumbs Gift Card", html, text)
    except Exception:
        current_app.logger.exception(
            "gift_card_email_failed gift_card_id=%s", getattr(card, "id", None)
        )


# ────────────────────────────────────────
# HOME
# ────────────────────────────────────────
@customer_bp.route("/")
def home():
    try:
        featured = (
            Product.query.filter_by(is_featured=True, is_active=True).limit(8).all()
        )
        enrich_products(featured)
        categories = Category.query.all()
    except SQLAlchemyError:
        db.session.rollback()
        featured = []
        categories = []
    occasions = ["Birthday", "Wedding", "Anniversary", "Baby Shower", "Corporate"]
    return render_template(
        "customer/home.html",
        featured=featured,
        categories=categories,
        occasions=occasions,
    )


# ────────────────────────────────────────
# PRODUCTS
# ────────────────────────────────────────
@customer_bp.route("/products")
def products():
    q = request.args.get("q", "")
    cat_id = request.args.get("category", type=int)
    eggless = request.args.get("eggless", type=int)
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    occasion = request.args.get("occasion", "")
    sort = request.args.get("sort", "recommended")
    page, per_page = page_args(default_per_page=24, max_per_page=48)

    pagination = get_customer_products_page(
        {
            "q": q,
            "category": cat_id,
            "eggless": eggless,
            "min_price": min_price,
            "max_price": max_price,
            "occasion": occasion,
            "sort": sort,
            "customer_id": current_user.id if current_user.is_authenticated else None,
        },
        page,
        per_page,
    )
    if current_user.is_authenticated and q:
        try:
            get_container().mcp_context_service.record_customer_activity(
                user_id=current_user.id,
                event_type="search",
                query_text=q,
                metadata={"sort": sort, "category_id": cat_id},
                request_obj=request,
            )
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
    categories = Category.query.all()

    def page_url(page_number):
        args = request.args.to_dict(flat=True)
        args["page"] = page_number
        return url_for("customer.products", **args)

    return render_template(
        "customer/products.html",
        products=pagination.items,
        pagination=pagination,
        categories=categories,
        q=q,
        cat_id=cat_id,
        eggless=eggless,
        min_price=min_price,
        max_price=max_price,
        occasion=occasion,
        sort=sort,
        page_url=page_url,
    )


@customer_bp.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_or_404(Product, product_id)
    if current_user.is_authenticated:
        try:
            container = get_container()
            container.mcp_context_service.record_customer_activity(
                user_id=current_user.id,
                event_type="product_view",
                product_id=product.id,
                metadata={
                    "product_name": product.name,
                    "category": product.category.name if product.category else "",
                },
                request_obj=request,
            )
            container.ai_assistant_service.maybe_create_recommendation_notification(
                current_user.id,
                product,
            )
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
    enrich_products([product])
    variants = product.variants.all()
    reviews = product.reviews.order_by(Review.created_at.desc()).all()
    in_wish = False
    can_review_product = False
    current_review = None
    if current_user.is_authenticated:
        in_wish = (
            Wishlist.query.filter_by(
                user_id=current_user.id, product_id=product_id
            ).first()
            is not None
        )
        if has_role(current_user, "customer"):
            current_review = Review.query.filter_by(
                product_id=product_id,
                user_id=current_user.id,
            ).first()
            can_review_product = has_delivered_product_order(
                current_user.id, product_id
            )

    # ML Recommendations & Related
    related = []
    from models import cache

    rec_ids = cache.get(f"recommendations_{product_id}")
    if rec_ids:
        # Maintain ML ordering
        unsorted_related = Product.query.filter(
            Product.id.in_(rec_ids), Product.is_active == True
        ).all()
        related = sorted(unsorted_related, key=lambda x: rec_ids.index(x.id))

    if len(related) < 4:
        from sqlalchemy import func

        fallback = (
            Product.query.filter(
                Product.category_id == product.category_id,
                Product.id != product.id,
                Product.id.notin_([r.id for r in related] + [0]),
                Product.is_active == True,
            )
            .order_by(func.random())
            .limit(4 - len(related))
            .all()
        )
        related.extend(fallback)

    enrich_products(related)

    return render_template(
        "customer/product_detail.html",
        product=product,
        variants=variants,
        reviews=reviews,
        in_wish=in_wish,
        related=related,
        preparation_steps=split_preparation_steps(product.preparation),
        can_review_product=can_review_product,
        current_review=current_review,
    )


# ────────────────────────────────────────
# CART
# ────────────────────────────────────────
@customer_bp.route("/cart")
def cart():
    items = get_cart_lines(current_user.id if current_user.is_authenticated else None)
    subtotal, total_quantity = calculate_cart_totals(items)
    free_delivery = compute_free_delivery_context(subtotal, has_items=bool(items))
    return render_template(
        "customer/cart.html",
        items=items,
        subtotal=subtotal,
        total_quantity=total_quantity,
        delivery_charge=free_delivery["delivery_charge"],
        delivery_threshold=free_delivery["delivery_threshold"],
        delivery_fee=free_delivery["delivery_fee"],
        amount_to_free_delivery=free_delivery["amount_to_free_delivery"],
        free_delivery_unlocked=free_delivery["free_delivery_unlocked"],
        free_delivery_progress=free_delivery["free_delivery_progress"],
    )


@customer_bp.route("/gift-cards", methods=["GET", "POST"])
@login_required
def gift_cards():
    if request.method == "POST":
        try:
            error = get_container().customer_risk_service.gift_card_purchase_error(
                current_user
            )
            if error:
                raise ValidationError(error)
        except ValidationError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("customer.gift_cards"))
        amount = request.form.get("amount", "0")
        recipient_email = (
            request.form.get("recipient_email") or current_user.email or ""
        ).strip()
        message = (request.form.get("message") or "").strip()
        try:
            with db.session.begin_nested():
                card = get_container().gift_card_service.issue(
                    amount=amount,
                    purchased_by_user_id=current_user.id,
                    recipient_email=recipient_email,
                    message=message,
                    actor_id=current_user.id,
                    reason="online_gift_card_purchase",
                )
            db.session.commit()
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("customer.gift_cards"))

        send_gift_card_email(card, recipient_email)
        flash(
            f"Gift card {card.code} created for ₹{Decimal(str(card.initial_value)):.2f}.",
            "success",
        )
        return redirect(url_for("customer.gift_cards"))

    owner_email = (current_user.email or "").strip().lower()
    cards = (
        GiftCard.query.filter(
            or_(
                GiftCard.purchased_by_user_id == current_user.id,
                func.lower(GiftCard.recipient_email) == owner_email,
            )
        )
        .order_by(GiftCard.issued_at.desc(), GiftCard.id.desc())
        .all()
    )
    available_balance = sum(
        Decimal(str(card.current_balance or 0))
        for card in cards
        if card.status == "active"
    )
    return render_template(
        "customer/gift_cards.html",
        cards=cards,
        available_balance=available_balance,
    )


@customer_bp.route("/cart/add", methods=["POST"])
def add_to_cart():
    product_id = request.form.get("product_id", type=int)
    variant_id = request.form.get("variant_id", type=int)
    quantity = max(request.form.get("quantity", 1, type=int) or 1, 1)

    product = db.get_or_404(Product, product_id)
    variant = resolve_product_variant(product, variant_id)

    if not variant or variant.stock < quantity:
        if wants_json_response():
            return jsonify({"ok": False, "message": "Insufficient stock."}), 400
        flash("Insufficient stock!", "danger")
        return redirect(request.referrer or url_for("customer.products"))

    if current_user.is_authenticated:
        existing = Cart.query.filter_by(
            user_id=current_user.id,
            product_id=product_id,
            variant_id=variant.id,
        ).first()

        if existing:
            existing.quantity = min(existing.quantity + quantity, variant.stock)
            cart_item = existing
        else:
            cart_item = Cart(
                user_id=current_user.id,
                product_id=product_id,
                variant_id=variant.id,
                quantity=quantity,
            )
            db.session.add(cart_item)
        db.session.commit()
        added_item = serialize_cart_line(
            product, variant, cart_item.quantity, cart_id=cart_item.id
        )
        summary_user_id = current_user.id
    else:
        added_item = upsert_guest_cart_item(product, variant, quantity)
        summary_user_id = None

    if wants_json_response():
        payload = build_cart_summary(summary_user_id, added_item=added_item)
        payload["ok"] = True
        payload["message"] = f"{product.name} added to cart."
        return jsonify(payload)

    if current_user.is_authenticated:
        flash(f"{product.name} added to cart! 🛒", "success")
    else:
        flash(
            f"{product.name} added to cart. Sign in when you are ready to checkout.",
            "success",
        )
    return redirect(request.referrer or url_for("customer.cart"))


@customer_bp.route("/cart/update", methods=["POST"])
def update_cart():
    quantity = max(request.form.get("quantity", type=int) or 1, 1)
    updated_line = None

    if current_user.is_authenticated:
        cart_id = request.form.get("cart_id", type=int)
        item = Cart.query.filter_by(id=cart_id, user_id=current_user.id).first_or_404()
        if quantity < 1:
            db.session.delete(item)
        else:
            item.quantity = min(
                quantity, item.variant.stock if item.variant else quantity
            )
        db.session.commit()
        if quantity >= 1:
            variant = item.variant or resolve_product_variant(
                item.product, item.variant_id
            )
            updated_line = serialize_cart_line(
                product=item.product,
                variant=variant,
                quantity=item.quantity,
                cart_id=item.id,
                is_guest=False,
            )
        summary_user_id = current_user.id
    else:
        product_id = request.form.get("product_id", type=int)
        variant_id = request.form.get("variant_id", type=int) or 0
        update_guest_cart_item(product_id, variant_id, quantity)
        summary_user_id = None
        updated_line = next(
            (
                line
                for line in get_cart_lines(None)
                if line["product_id"] == product_id
                and (line["variant_id"] or 0) == variant_id
            ),
            None,
        )

    if wants_json_response():
        lines = get_cart_lines(summary_user_id)
        subtotal, total_quantity = calculate_cart_totals(lines)
        free_delivery = compute_free_delivery_context(subtotal, has_items=bool(lines))
        payload = {
            "ok": True,
            "count": total_quantity,
            "line_count": len(lines),
            "subtotal": float(subtotal),
            "delivery_charge": float(free_delivery["delivery_charge"]),
            "grand_total": float(subtotal + free_delivery["delivery_charge"]),
            "empty": len(lines) == 0,
            "delivery_threshold": float(free_delivery["delivery_threshold"]),
            "amount_to_free_delivery": float(free_delivery["amount_to_free_delivery"]),
            "free_delivery_unlocked": free_delivery["free_delivery_unlocked"],
            "free_delivery_progress": free_delivery["free_delivery_progress"],
        }
        if updated_line:
            payload["item"] = {
                "quantity": updated_line["quantity"],
                "line_total": float(updated_line["line_total"]),
                "max_qty": int(updated_line["max_qty"]),
            }
        return jsonify(payload)

    return redirect(url_for("customer.cart"))


@customer_bp.route("/cart/remove/<int:cart_id>")
def remove_from_cart(cart_id):
    if current_user.is_authenticated:
        item = Cart.query.filter_by(id=cart_id, user_id=current_user.id).first_or_404()
        db.session.delete(item)
        db.session.commit()
    else:
        product_id = request.args.get("product_id", type=int)
        variant_id = request.args.get("variant_id", type=int) or 0
        update_guest_cart_item(product_id, variant_id, 0)
    flash("Item removed from cart.", "info")
    return redirect(url_for("customer.cart"))


# ────────────────────────────────────────
# WISHLIST
# ────────────────────────────────────────
@customer_bp.route("/wishlist")
@login_required
def wishlist():
    page, per_page = page_args(default_per_page=12, max_per_page=24)
    pagination = get_customer_wishlist_page(current_user.id, page, per_page)
    return render_template(
        "customer/wishlist.html", items=pagination.items, pagination=pagination
    )


@customer_bp.route("/wishlist/toggle/<int:product_id>")
@login_required
def toggle_wishlist(product_id):
    db.get_or_404(Product, product_id)
    item = Wishlist.query.filter_by(
        user_id=current_user.id, product_id=product_id
    ).first()
    if item:
        db.session.delete(item)
        flash("Removed from wishlist.", "info")
    else:
        db.session.add(Wishlist(user_id=current_user.id, product_id=product_id))
        flash("Added to wishlist! ❤️", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("customer.wishlist"))


# ────────────────────────────────────────
# CHECKOUT & ORDERS
# ────────────────────────────────────────
@customer_bp.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("customer.cart"))

    if request.method == "POST":
        try:
            get_container().customer_risk_service.ensure_can_purchase(current_user)
        except ValidationError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("customer.cart"))
        try:
            added_addons = apply_checkout_addons(current_user.id, request.form)
            if added_addons:
                db.session.flush()
                cart_items = Cart.query.filter_by(user_id=current_user.id).all()
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("customer.checkout"))

    subtotal = sum(
        get_container().pricing_service.resolve_product_price(i.product, i.variant)[
            "price"
        ]
        * i.quantity
        for i in cart_items
    )

    # Apply membership discount
    discount = Decimal("0")
    sub = Subscription.query.filter_by(user_id=current_user.id, is_active=True).first()
    if sub and sub.end_date > utcnow():
        discount = (subtotal * sub.discount_pct / 100).quantize(Decimal("0.01"))

    free_delivery = compute_free_delivery_context(subtotal, has_items=bool(cart_items))
    delivery_threshold = free_delivery["delivery_threshold"]
    delivery_fee = free_delivery["delivery_fee"]
    delivery_charge = free_delivery["delivery_charge"]
    finance_service = get_container().finance_service
    gst_rate = finance_service.resolve_active_sales_tax_rate()
    gst_preview = finance_service.calculate_sales_gst(
        subtotal,
        discount=discount,
        rate_percent=gst_rate,
    )
    gst_amount = gst_preview["gst_amount"]
    taxable_amount = gst_preview["taxable_amount"]
    loyalty_balance = current_user.loyalty_points
    loyalty_rules = get_loyalty_config()
    loyalty_preview = calculate_loyalty_redemption(
        max(loyalty_balance, loyalty_rules["LOYALTY_REDEEM_PER"]),
        subtotal,
        None,
    )
    total = subtotal - discount + gst_amount + delivery_charge

    slot_service = get_container().slot_service
    time_slots = current_app.config["TIME_SLOTS"]
    pickup_available_slots = slot_service.get_available_slots(utcnow().date())
    pickup_opening_time, pickup_closing_time = slot_service.business_hours_range()
    saved_addresses = get_saved_addresses_for_user(current_user.id)
    checkout_addons = get_container().mcp_context_service.get_checkout_addons(
        cart_items,
        limit=6,
    )
    default_saved_address = next(
        (addr for addr in saved_addresses if addr.is_default),
        saved_addresses[0] if saved_addresses else None,
    )
    selected_address_id = default_saved_address.id if default_saved_address else None
    fulfillment_type = "DELIVERY"
    checkout_address = (
        extract_address_payload(
            {},
            fallback_address=default_saved_address,
            default_phone=current_user.phone or "",
        )
        if default_saved_address
        else {
            "label": "Saved Address",
            "address_line1": "",
            "address_line2": "",
            "city": "",
            "pincode": "",
            "phone": current_user.phone or "",
            "latitude": None,
            "longitude": None,
        }
    )

    if request.method == "POST":
        fulfillment_type = (
            (request.form.get("fulfillment_type") or "DELIVERY").strip().upper()
        )
        if fulfillment_type not in {"DELIVERY", "PICKUP"}:
            flash(
                "Please choose whether this order is for delivery or pickup.", "danger"
            )
            return redirect(url_for("customer.checkout"))

        coupon_code = request.form.get("coupon_code", "").strip().upper()
        coupon_discount = Decimal("0")
        loyalty_points_requested = request.form.get("loyalty_points", type=int) or 0
        loyalty_points_applied = 0
        loyalty_discount = Decimal("0")
        risk_service = get_container().customer_risk_service
        if coupon_code and risk_service.promotion_error(current_user):
            flash(
                "Promotional offers are not available for this account.", "warning"
            )
            coupon_code = ""
        if loyalty_points_requested and risk_service.loyalty_error(current_user):
            flash("Loyalty rewards are not available for this account.", "warning")
            return redirect(url_for("customer.checkout"))
        selected_address_id = request.form.get("selected_address_id", type=int)
        selected_saved_address = get_selected_saved_address(
            current_user.id, selected_address_id
        )
        checkout_address = extract_address_payload(
            request.form,
            fallback_address=selected_saved_address,
            default_phone=current_user.phone or "",
        )
        selected_time_slot = ""
        scheduled_for = None
        order_contact_phone = (
            current_user.phone or checkout_address.get("phone") or ""
        ).strip()
        delivery_target_date = None
        applied_delivery_charge = delivery_charge

        if fulfillment_type == "DELIVERY":
            delivery_date_raw = request.form.get("delivery_date", "").strip()
            try:
                delivery_target_date = datetime.strptime(
                    delivery_date_raw, "%Y-%m-%d"
                ).date()
            except ValueError:
                flash("Please select a valid delivery date.", "danger")
                return redirect(url_for("customer.checkout"))

            try:
                selected_time_slot = slot_service.validate_delivery_selection(
                    delivery_target_date,
                    request.form.get("time_slot", ""),
                )
            except ValidationError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("customer.checkout"))

            address_errors = validate_address_payload(checkout_address)
            if address_errors:
                flash(address_errors[0], "danger")
                return redirect(url_for("customer.checkout"))

            order_contact_phone = (
                checkout_address.get("phone") or current_user.phone or ""
            ).strip()
            scheduled_for = slot_service.scheduled_datetime_for_selection(
                delivery_target_date,
                selected_slot=selected_time_slot,
            )
        else:
            pickup_date_raw = request.form.get("pickup_date", "").strip()
            custom_pickup_time = request.form.get("custom_pickup_time", "").strip()
            pickup_phone = (
                request.form.get("pickup_phone") or current_user.phone or ""
            ).strip()
            if not pickup_phone:
                flash("Please provide a phone number for pickup updates.", "danger")
                return redirect(url_for("customer.checkout"))
            try:
                delivery_target_date = datetime.strptime(
                    pickup_date_raw, "%Y-%m-%d"
                ).date()
            except ValueError:
                flash("Please choose a valid pickup date.", "danger")
                return redirect(url_for("customer.checkout"))

            try:
                selected_time_slot = slot_service.validate_pickup_selection(
                    delivery_target_date,
                    selected_slot=request.form.get("pickup_slot", ""),
                    custom_time=custom_pickup_time,
                )
                scheduled_for = slot_service.scheduled_datetime_for_selection(
                    delivery_target_date,
                    selected_slot=request.form.get("pickup_slot", ""),
                    custom_time=custom_pickup_time,
                )
            except ValidationError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("customer.checkout"))

            order_contact_phone = pickup_phone
            applied_delivery_charge = Decimal("0")

        try:
            validate_preorder_requirements(cart_items, scheduled_for)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("customer.checkout"))

        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            prior_order_count = Order.query.filter_by(user_id=current_user.id).count()
            prior_coupon_uses = Order.query.filter_by(
                user_id=current_user.id,
                coupon_code=coupon_code,
            ).count()
            eligibility_message = (
                coupon.eligibility_message(prior_order_count) if coupon else None
            )
            if (
                coupon
                and coupon.is_valid()
                and subtotal >= coupon.min_order_value
                and eligibility_message is None
                and prior_coupon_uses < int(coupon.per_user_limit or 1)
            ):
                if coupon.discount_type == "percentage":
                    coupon_discount = (subtotal * coupon.discount_value / 100).quantize(
                        Decimal("0.01")
                    )
                else:
                    coupon_discount = coupon.discount_value
                coupon.used_count += 1
            elif coupon_code:
                flash(
                    eligibility_message or "Invalid or expired coupon code.",
                    "warning",
                )
                if coupon and prior_coupon_uses >= int(coupon.per_user_limit or 1):
                    db.session.add(
                        FraudAlert(
                            user_id=current_user.id,
                            alert_type="coupon_abuse_attempt",
                            severity="medium",
                            details=f"Coupon {coupon_code} reuse attempted beyond per-user limit.",
                        )
                    )

        loyalty_result = calculate_loyalty_redemption(
            loyalty_points_requested, subtotal, loyalty_balance
        )
        loyalty_points_applied = loyalty_result["points_applied"]
        loyalty_discount = Decimal(str(loyalty_result["discount"]))
        if (
            loyalty_points_requested
            and loyalty_points_requested % loyalty_result["redeem_per"] != 0
        ):
            flash(
                "Loyalty points can be redeemed only in multiples of "
                f"{loyalty_result['redeem_per']}.",
                "warning",
            )
            return redirect(url_for("customer.checkout"))
        if loyalty_points_requested and loyalty_result.get("below_minimum"):
            flash(
                "Orders above ₹{threshold} need at least {points} points "
                "(₹{discount:.2f}) to redeem.".format(
                    threshold=loyalty_result["min_order_value"],
                    points=loyalty_result["min_points_required"],
                    discount=loyalty_result["min_required_discount"],
                ),
                "warning",
            )
            return redirect(url_for("customer.checkout"))
        if loyalty_points_requested and loyalty_points_applied <= 0:
            flash("Those loyalty points cannot be applied to this order.", "warning")
            return redirect(url_for("customer.checkout"))

        total_discount = discount + coupon_discount + loyalty_discount
        gst_payload = finance_service.sales_gst_context(
            subtotal,
            discount=discount + coupon_discount,
            loyalty_discount=loyalty_discount,
            rate_percent=gst_rate,
            channel="online",
            source="WEB",
            fulfillment_type=fulfillment_type,
        )
        gst_amount = gst_payload["gst_amount"]
        taxable_amount = gst_payload["taxable_amount"]
        payable_before_gift_card = (
            subtotal - total_discount + gst_amount + applied_delivery_charge
        ).quantize(Decimal("0.01"))
        gift_card_code = request.form.get("gift_card_code", "").strip().upper()
        gift_card_redemption_amount = Decimal("0")
        final_total = payable_before_gift_card

        default_branch_id = current_app.config.get("DEFAULT_BRANCH_ID")
        stock_update_variant_ids = []
        stock_update_material_ids = []

        # Lock rows to prevent race conditions during checkout
        for item in cart_items:
            v = (
                db.session.get(ProductVariant, item.variant_id, with_for_update=True)
                if item.variant
                else None
            )
            if item.variant and (not v or v.stock < item.quantity):
                flash(f"Sorry, {item.product.name} is out of stock.", "danger")
                db.session.rollback()
                return redirect(url_for("customer.cart"))

        payment_link = None
        try:
            with db.session.begin_nested():
                order_service = get_container().order_service
                gift_card_service = get_container().gift_card_service
                lines = [
                    order_service.build_line_from_cart_item(
                        item,
                        unit_price=get_container().pricing_service.resolve_product_price(
                            item.product,
                            item.variant,
                        )[
                            "price"
                        ],
                    )
                    for item in cart_items
                ]
                store_details = current_app.config["STORE_DETAILS"]
                if fulfillment_type == "PICKUP":
                    address_line1 = store_details.get("address_line1", "")
                    address_line2 = store_details.get("address_line2", "")
                    city = store_details.get("city", "")
                    pincode = store_details.get("pincode", "")
                    delivery_latitude = None
                    delivery_longitude = None
                else:
                    address_line1 = checkout_address["address_line1"]
                    address_line2 = checkout_address["address_line2"]
                    city = checkout_address["city"]
                    pincode = checkout_address["pincode"]
                    delivery_latitude = checkout_address.get("latitude")
                    delivery_longitude = checkout_address.get("longitude")

                if gift_card_code:
                    gift_card_preview = gift_card_service.preview_redemption(
                        gift_card_code,
                        payable_before_gift_card,
                        lock=True,
                    )
                    gift_card_redemption_amount = gift_card_preview["amount"]
                    final_total = (
                        payable_before_gift_card - gift_card_redemption_amount
                    ).quantize(Decimal("0.01"))

                requested_payment_method = request.form.get("payment_method", "COD")
                payment_method = (
                    "GIFT_CARD"
                    if final_total == Decimal("0.00") and gift_card_code
                    else requested_payment_method
                )
                payment_status = (
                    "PAID"
                    if final_total == Decimal("0.00") and gift_card_code
                    else "PENDING"
                )

                risk_service.ensure_can_purchase(
                    current_user, payment_method=requested_payment_method
                )

                creation = order_service.create_order(
                    user_id=current_user.id,
                    branch_id=default_branch_id,
                    lines=lines,
                    subtotal=subtotal,
                    discount=discount + coupon_discount,
                    loyalty_discount=loyalty_discount,
                    delivery_charge=applied_delivery_charge,
                    gst_rate=gst_rate,
                    gst_amount=gst_amount,
                    gst_taxable_amount=gst_payload["taxable_amount"],
                    cgst_amount=gst_payload["cgst_amount"],
                    sgst_amount=gst_payload["sgst_amount"],
                    gst_supply_type=gst_payload["gst_supply_type"],
                    gst_order_source=gst_payload["gst_order_source"],
                    gst_liability_party=gst_payload["gst_liability_party"],
                    gst_return_bucket=gst_payload["gst_return_bucket"],
                    gst_invoice_note=gst_payload["gst_invoice_note"],
                    ecommerce_operator=gst_payload["ecommerce_operator"],
                    ecommerce_tcs_amount=gst_payload["ecommerce_tcs_amount"],
                    total=final_total,
                    gift_card_redemption_amount=gift_card_redemption_amount,
                    gift_card_code=(
                        gift_card_code if gift_card_redemption_amount > 0 else None
                    ),
                    fulfillment_type=fulfillment_type,
                    address_line1=address_line1,
                    address_line2=address_line2,
                    city=city,
                    pincode=pincode,
                    phone=order_contact_phone,
                    delivery_latitude=delivery_latitude,
                    delivery_longitude=delivery_longitude,
                    delivery_slot=selected_time_slot,
                    delivery_date=delivery_target_date,
                    special_note=request.form.get("special_note"),
                    occasion=request.form.get("occasion"),
                    payment_method=payment_method,
                    payment_status=payment_status,
                    status="PLACED",
                    channel="online",
                    source="WEB",
                    coupon_code=coupon_code if coupon_discount > 0 else None,
                    payment_reason="online_checkout",
                )
                order = creation.order
                stock_update_variant_ids = creation.stock_update_variant_ids
                stock_update_material_ids = creation.stock_update_material_ids

                if risk_service.order_needs_manual_approval(current_user):
                    order.status = "ON_HOLD"
                    order.mark_status_change()
                    db.session.add(
                        FraudAlert(
                            order_id=order.id,
                            user_id=current_user.id,
                            alert_type="requires_manual_approval",
                            severity="medium",
                            details=(
                                "Order placed by a restricted customer and requires "
                                "manual approval before fulfilment."
                            ),
                        )
                    )

                if gift_card_redemption_amount > 0:
                    gift_card_service.redeem(
                        gift_card_code,
                        order,
                        payable_before_gift_card,
                        actor_id=current_user.id,
                    )

                suspicious_order_count = Order.query.filter(
                    Order.user_id == current_user.id,
                    Order.placed_at >= utcnow() - timedelta(minutes=10),
                    Order.total == final_total,
                ).count()
                if suspicious_order_count >= 2:
                    order.is_suspicious = True
                    db.session.add(
                        FraudAlert(
                            order_id=order.id,
                            user_id=current_user.id,
                            alert_type="rapid_repeat_order",
                            severity="high",
                            details="Multiple matching-value orders were placed within a short time window.",
                        )
                    )
                    get_container().audit_service.alert(
                        "fraud_detected",
                        "Suspicious repeat order",
                        f"User {current_user.id} placed duplicate-value orders rapidly.",
                        severity="high",
                        user_id=current_user.id,
                    )

                if loyalty_points_applied > 0:
                    get_container().loyalty_service.redeem_for_order(
                        current_user.id,
                        order.id,
                        loyalty_points_applied,
                        subtotal,
                    )

                if (
                    order.payment_method in ["UPI", "CARD"]
                    and Decimal(str(order.total or 0)) > 0
                ):
                    payment_link = create_order_payment_link(order)

                if request.form.get("save_address_for_future"):
                    save_address_for_customer(
                        user_id=current_user.id,
                        payload=checkout_address,
                        make_default=bool(request.form.get("make_default")),
                    )

                Cart.query.filter_by(user_id=current_user.id).delete()
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("customer.cart"))

        notify(
            current_user.id,
            "Order Placed! 🎉",
            f"Your order #{order.order_number} has been placed successfully.",
            "order",
            url_for("customer.order_detail", order_id=order.id),
        )
        db.session.commit()

        emit_new_order(order)
        for variant_id in set(stock_update_variant_ids):
            variant = db.session.get(ProductVariant, variant_id)
            if variant:
                emit_stock_updated(variant, include_customer=True)
        for material_id in set(stock_update_material_ids):
            material = db.session.get(RawMaterial, material_id)
            if material:
                emit_stock_updated(material)

        try:
            from tasks.operations import generate_invoice_pdf

            generate_invoice_pdf.delay(order.id)
        except Exception:
            current_app.logger.exception(
                "invoice_task_enqueue_failed order_id=%s", order.id
            )
        try:
            send_order_placed_email(order)
            send_order_sms(order)
            send_order_whatsapp(order)
        except Exception:
            current_app.logger.exception(
                "Failed to dispatch order placement notifications for %s", order.id
            )
        if payment_link:
            flash(
                "Order created. Complete payment after the gateway is integrated using the payment page below.",
                "info",
            )
            return redirect(
                url_for("customer.payment_link_page", token=payment_link.token)
            )

        flash(f"Order #{order.order_number} placed successfully!", "success")
        return redirect(url_for("customer.order_detail", order_id=order.id))

    return render_template(
        "customer/checkout.html",
        cart_items=cart_items,
        subtotal=subtotal,
        discount=discount,
        delivery_charge=delivery_charge,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        taxable_amount=taxable_amount,
        total=total,
        time_slots=time_slots,
        pickup_available_slots=pickup_available_slots,
        pickup_opening_time=pickup_opening_time.strftime("%H:%M"),
        pickup_closing_time=pickup_closing_time.strftime("%H:%M"),
        pickup_buffer_minutes=current_app.config.get("PICKUP_BUFFER_MINUTES", 20),
        has_subscription=bool(sub),
        saved_addresses=saved_addresses,
        selected_address_id=selected_address_id,
        fulfillment_type=fulfillment_type,
        checkout_address=checkout_address,
        loyalty_balance=loyalty_balance,
        loyalty_preview=loyalty_preview,
        loyalty_rules=loyalty_rules,
        delivery_threshold=delivery_threshold,
        delivery_fee=delivery_fee,
        amount_to_free_delivery=free_delivery["amount_to_free_delivery"],
        free_delivery_unlocked=free_delivery["free_delivery_unlocked"],
        free_delivery_progress=free_delivery["free_delivery_progress"],
        earliest_pickup_date=utcnow().date().isoformat(),
        earliest_delivery_date=utcnow().date().isoformat(),
        checkout_addons=checkout_addons,
    )


@customer_bp.route("/orders")
@login_required
def order_history():
    page, per_page = page_args(default_per_page=8, max_per_page=16)
    pagination = get_customer_orders_page(current_user.id, page, per_page)
    if wants_json_response():
        return jsonify(
            {
                "fragments": {
                    "#customer-orders-live": render_template(
                        "customer/_orders_live.html",
                        orders=pagination.items,
                        pagination=pagination,
                    ),
                }
            }
        )
    return render_template(
        "customer/orders.html", orders=pagination.items, pagination=pagination
    )


@customer_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    context = build_order_detail_context(order)
    if wants_json_response():
        return jsonify(
            {
                "fragments": {
                    "#customer-order-live": render_template(
                        "customer/_order_detail_live.html",
                        **context,
                    ),
                }
            }
        )
    return render_template("customer/order_detail.html", **context)


@customer_bp.route("/payments/<token>")
@login_required
def payment_link_page(token):
    payment_link = PaymentLink.query.filter_by(token=token).first_or_404()
    if (
        not has_role(current_user, *ADMIN_PORTAL_ROLES)
        and payment_link.user_id != current_user.id
    ):
        abort(403)

    return render_template(
        "customer/payment_link.html",
        payment_link=payment_link,
        related_order=payment_link.order,
    )


@customer_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_cancel():
        flash(
            "Order cannot be cancelled at this stage (must be within 2 minutes of placing).",
            "danger",
        )
        return redirect(url_for("customer.order_detail", order_id=order_id))

    reason = "Customer cancelled within quick-cancel window"
    try:
        result = get_container().order_reversal_service.cancel_or_refund_order(
            order,
            reason=reason,
            actor_id=current_user.id,
            reverse_stock=True,
            allow_paid_refund=((order.payment_status or "").upper() == "PAID"),
            initiated_by="customer",
        )
        notify(
            current_user.id,
            (
                "Order Refunded"
                if result["action"] == "order_refunded"
                else "Order Cancelled"
            ),
            f"Order #{order.order_number} has been {order.status.lower()}.",
            "payment" if result["action"] == "order_refunded" else "order",
            url_for("customer.order_detail", order_id=order.id),
        )
        get_container().push_service.send_to_user(
            current_user.id,
            (
                "Order Refunded"
                if result["action"] == "order_refunded"
                else "Order Cancelled"
            ),
            f"Order #{order.order_number} has been {order.status.lower()}.",
            data={"order_id": order.id, "status": order.status},
        )
        db.session.commit()
        if result["action"] == "order_refunded":
            emit_order_refunded(order, reason=reason)
        else:
            emit_order_cancelled(order, reason=reason)
        for variant_id in set(result.get("restored_variant_ids", [])):
            variant = db.session.get(ProductVariant, variant_id)
            if variant:
                emit_stock_updated(variant, include_customer=True)
        for movement in result.get("stock_movements", []):
            if movement and movement.raw_material:
                emit_stock_updated(movement.raw_material)
        flash("Order cancelled successfully.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception(
            "customer_order_cancel_failed order_id=%s", order.id
        )
        flash("Unable to cancel the order right now.", "danger")
    return redirect(url_for("customer.order_history"))


@customer_bp.route("/orders/<int:order_id>/reorder")
@login_required
def reorder(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    added = 0
    skipped = []
    for item in order.items.all():
        variant = (
            db.session.get(ProductVariant, item.variant_id) if item.variant_id else None
        )
        if variant and variant.stock > 0:
            quantity_to_add = min(item.quantity, variant.stock)
            existing = Cart.query.filter_by(
                user_id=current_user.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
            ).first()
            if existing:
                existing.quantity = min(
                    existing.quantity + quantity_to_add, variant.stock
                )
            else:
                db.session.add(
                    Cart(
                        user_id=current_user.id,
                        product_id=item.product_id,
                        variant_id=item.variant_id,
                        quantity=quantity_to_add,
                    )
                )
            added += quantity_to_add
        else:
            skipped.append(item.product_name)
    db.session.commit()
    if added:
        flash(f"{added} item(s) added to cart!", "success")
    if skipped:
        flash(
            "Some previous items are unavailable right now: " + ", ".join(skipped[:3]),
            "warning",
        )
    return redirect(url_for("customer.cart"))


@customer_bp.route("/orders/<int:order_id>/change-address", methods=["POST"])
@login_required
def change_address(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_change_address():
        flash("Address cannot be changed at this stage.", "danger")
        return redirect(url_for("customer.order_detail", order_id=order_id))

    old_addr = (
        f"{order.address_line1}, {order.address_line2}, {order.city} - {order.pincode}"
    )
    order.address_line1 = request.form.get("address_line1", order.address_line1)
    order.address_line2 = request.form.get("address_line2", order.address_line2)
    order.city = request.form.get("city", order.city)
    order.pincode = request.form.get("pincode", order.pincode)
    order.address_changes += 1

    new_addr = (
        f"{order.address_line1}, {order.address_line2}, {order.city} - {order.pincode}"
    )
    db.session.add(
        AddressChange(
            order_id=order.id,
            old_address=old_addr,
            new_address=new_addr,
            changed_by=current_user.id,
        )
    )
    db.session.commit()
    flash("Delivery address updated!", "success")
    return redirect(url_for("customer.order_detail", order_id=order_id))


@customer_bp.route("/orders/<int:order_id>/modify", methods=["POST"])
@login_required
def request_modification(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_modify():
        flash("Order cannot be modified at this stage.", "danger")
        return redirect(url_for("customer.order_detail", order_id=order_id))

    description = request.form.get("description", "")
    order.is_locked = True
    db.session.add(
        ModificationRequest(
            order_id=order.id, user_id=current_user.id, description=description
        )
    )
    db.session.commit()
    flash("Modification request submitted. Admin will review shortly.", "success")
    return redirect(url_for("customer.order_detail", order_id=order_id))


# ────────────────────────────────────────
# REVIEWS
# ────────────────────────────────────────
@customer_bp.route("/review/add", methods=["POST"])
@login_required
def add_review():
    product_id = request.form.get("product_id", type=int)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "")

    if not has_role(current_user, "customer"):
        flash("Only customers can submit reviews.", "danger")
        return redirect(url_for("customer.product_detail", product_id=product_id))

    if not rating or rating < 1 or rating > 5:
        flash("Please choose a rating between 1 and 5.", "danger")
        return redirect(url_for("customer.product_detail", product_id=product_id))

    if not has_delivered_product_order(current_user.id, product_id):
        flash(
            "Reviews can be added only after this product has been delivered to you.",
            "warning",
        )
        return redirect(url_for("customer.product_detail", product_id=product_id))

    existing = Review.query.filter_by(
        product_id=product_id, user_id=current_user.id
    ).first()
    if existing:
        existing.rating = rating
        existing.comment = comment
    else:
        db.session.add(
            Review(
                product_id=product_id,
                user_id=current_user.id,
                rating=rating,
                comment=comment,
            )
        )
    db.session.commit()
    flash("Review submitted! Thank you.", "success")
    return redirect(url_for("customer.product_detail", product_id=product_id))


# ────────────────────────────────────────
# MESSAGES / CHAT
# ────────────────────────────────────────
@customer_bp.route("/chat")
@login_required
def chat():
    messages = (
        Message.query.filter(customer_support_thread_filter(current_user.id))
        .order_by(Message.sent_at.asc())
        .all()
    )

    # Mark as read
    staff_ids = support_staff_ids()
    if staff_ids:
        Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.sender_id.in_(staff_ids),
            Message.is_read.is_(False),
        ).update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    return render_template(
        "customer/chat.html",
        messages=messages,
        support_recipient=support_recipient(),
        support_staff=support_staff_members(),
    )


@customer_bp.route("/chat/send", methods=["POST"])
@login_required
def send_message():
    content = request.form.get("content", "").strip()
    recipient = support_recipient()
    if content and recipient:
        message = Message(
            sender_id=current_user.id,
            receiver_id=recipient.id,
            content=content,
        )
        db.session.add(message)
        db.session.flush()
        notify(
            recipient.id,
            f"Support message from {current_user.name}",
            content[:100],
            "chat",
            url_for("admin.chat_thread", customer_id=current_user.id),
        )
        db.session.commit()
        emit_support_message(message, current_user.id)
    elif content:
        flash("Support is temporarily unavailable. Please call the bakery.", "warning")
    return redirect(url_for("customer.chat"))


@customer_bp.route("/chat/ai", methods=["POST"])
@csrf.exempt
def ai_recommend():
    payload = request.get_json(silent=True) or {}
    surface = payload.get("surface") or "customer"
    if not current_user.is_authenticated:
        return jsonify(ai_auth_required_payload(surface, expired=True)), 401
    if not can_use_customer_ai(current_user):
        return (
            jsonify(
                {
                    "ok": False,
                    "code": "forbidden",
                    "message": "This AI assistant is available only to customer accounts.",
                }
            ),
            403,
        )
    ai_error = get_container().customer_risk_service.ai_error(current_user)
    if ai_error:
        return (
            jsonify(
                {
                    "ok": False,
                    "code": "forbidden",
                    "message": ai_error,
                }
            ),
            403,
        )

    query = (payload.get("query") or "").strip()
    if not query:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Tell us what kind of bakery item you are looking for.",
                }
            ),
            400,
        )

    history = payload.get("history") or []
    if not isinstance(history, list):
        history = []
    history = [
        {
            "role": str(turn.get("role"))[:16] if isinstance(turn, dict) else "",
            "content": str(turn.get("content"))[:500] if isinstance(turn, dict) else "",
        }
        for turn in history[-12:]
        if isinstance(turn, dict)
        and str(turn.get("role")) in {"user", "assistant"}
        and turn.get("content")
    ]

    user_id = current_user.id
    container = get_container()
    try:
        container.mcp_context_service.record_customer_activity(
            user_id=user_id,
            event_type="ai_query",
            query_text=query,
            metadata={"surface": surface},
            request_obj=request,
        )
        result = container.ai_assistant_service.answer_customer_request(
            user_id,
            query,
            limit=6,
            history=history,
        )
        if has_role(current_user, "customer"):
            messages = container.ai_assistant_service.store_support_exchange(
                current_user.id,
                query,
                result["message"],
            )
        else:
            messages = []
        db.session.commit()
        for message in messages:
            emit_support_message(message, current_user.id)
    except SQLAlchemyError:
        db.session.rollback()
        engine = get_recommendation_engine()
        products, message = engine.recommend(user_id, query, limit=6)
        result = {
            "ok": True,
            "source": "rules",
            "model": "rule-based fallback",
            "message": message,
            "products": [
                container.mcp_context_service.compact_product(product)
                for product in products
            ],
            "checkout_addons": [],
            "context_tools": [],
        }
    result["products"] = [
        serialize_ai_product_payload(product) for product in result.get("products", [])
    ]
    result["checkout_addons"] = [
        serialize_ai_product_payload(product)
        for product in result.get("checkout_addons", [])
    ]
    return jsonify(result)


# ────────────────────────────────────────
# NOTIFICATIONS
# ────────────────────────────────────────
@customer_bp.route("/notifications")
@login_required
def notifications():
    notifs = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return render_template("customer/notifications.html", notifs=notifs)


# ────────────────────────────────────────
# SUBSCRIPTIONS
# ────────────────────────────────────────
@customer_bp.route("/subscription")
@login_required
def subscription():
    sub = Subscription.query.filter_by(user_id=current_user.id, is_active=True).first()
    pending_subscription_payment = (
        PaymentLink.query.filter_by(
            user_id=current_user.id,
            purpose="SUBSCRIPTION",
            status="PENDING",
        )
        .order_by(PaymentLink.id.desc())
        .first()
    )
    return render_template(
        "customer/subscription.html",
        sub=sub,
        pending_subscription_payment=pending_subscription_payment,
    )


@customer_bp.route("/subscription/subscribe", methods=["POST"])
@login_required
def subscribe():
    plan = request.form.get("plan", "monthly")
    prices = {"monthly": (199, 10, 30), "yearly": (1499, 15, 365)}
    price, disc, days = prices.get(plan, prices["monthly"])
    payment_link = create_subscription_payment_link(plan, price, disc, days)
    db.session.commit()
    flash(
        "Payment page opened. Membership will stay inactive until the payment gateway is connected and confirms success.",
        "info",
    )
    return redirect(url_for("customer.payment_link_page", token=payment_link.token))


@customer_bp.route("/subscriptions")
@login_required
def recurring_subscriptions():
    subscriptions = (
        RecurringSubscription.query.filter_by(user_id=current_user.id)
        .order_by(RecurringSubscription.created_at.desc())
        .all()
    )
    subscription_ids = [subscription.id for subscription in subscriptions]
    logs = []
    if subscription_ids:
        logs = (
            SubscriptionOrderLog.query.filter(
                SubscriptionOrderLog.subscription_id.in_(subscription_ids)
            )
            .order_by(SubscriptionOrderLog.attempted_at.desc())
            .limit(30)
            .all()
        )
    variants = (
        ProductVariant.query.join(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.name.asc(), ProductVariant.name.asc())
        .all()
    )
    return render_template(
        "customer/subscriptions.html",
        subscriptions=subscriptions,
        logs=logs,
        variants=variants,
    )


@customer_bp.route("/subscriptions/create", methods=["POST"])
@login_required
def create_recurring_subscription():
    variant_id = request.form.get("variant_id", type=int)
    quantity = max(1, request.form.get("quantity", type=int) or 1)
    frequency = (request.form.get("frequency") or "weekly").strip().lower()
    if frequency not in {"daily", "weekly", "monthly", "custom"}:
        frequency = "weekly"
    days_of_week = ",".join(
        sorted(
            {
                raw
                for raw in request.form.getlist("days_of_week")
                if raw in {"0", "1", "2", "3", "4", "5", "6"}
            }
        )
    )
    next_date_raw = (request.form.get("next_scheduled_date") or "").strip()
    try:
        next_date = datetime.strptime(next_date_raw, "%Y-%m-%d").date()
    except ValueError:
        next_date = utcnow().date() + timedelta(days=1)
    variant = db.session.get(ProductVariant, variant_id)
    if variant is None or variant.product is None:
        flash("Choose a valid product for the recurring order.", "danger")
        return redirect(url_for("customer.recurring_subscriptions"))

    subscription = RecurringSubscription(
        user_id=current_user.id,
        branch_id=current_app.config.get("DEFAULT_BRANCH_ID"),
        status="active",
        frequency=frequency,
        days_of_week=days_of_week if frequency == "custom" else None,
        next_scheduled_date=next_date,
        payment_method_reference="manual_payment_link",
        delivery_window=(request.form.get("delivery_window") or "").strip()
        or "Subscription delivery",
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(subscription)
    db.session.flush()
    db.session.add(
        SubscriptionItem(
            subscription_id=subscription.id,
            product_id=variant.product_id,
            variant_id=variant.id,
            quantity=quantity,
        )
    )
    db.session.commit()
    flash(
        "Recurring order created. Each cycle will create a payment-pending order until saved recurring payments are integrated.",
        "success",
    )
    return redirect(url_for("customer.recurring_subscriptions"))


@customer_bp.route("/subscriptions/<int:subscription_id>/update", methods=["POST"])
@login_required
def update_recurring_subscription(subscription_id):
    subscription = RecurringSubscription.query.filter_by(
        id=subscription_id,
        user_id=current_user.id,
    ).first_or_404()
    item = subscription.items.order_by(SubscriptionItem.id.asc()).first()
    variant_id = request.form.get("variant_id", type=int)
    quantity = max(1, request.form.get("quantity", type=int) or 1)
    variant = db.session.get(ProductVariant, variant_id)
    if variant is None or variant.product is None:
        flash("Choose a valid product.", "danger")
        return redirect(url_for("customer.recurring_subscriptions"))
    if item is None:
        item = SubscriptionItem(subscription_id=subscription.id)
        db.session.add(item)
    item.product_id = variant.product_id
    item.variant_id = variant.id
    item.quantity = quantity
    frequency = (
        (request.form.get("frequency") or subscription.frequency).strip().lower()
    )
    if frequency in {"daily", "weekly", "monthly", "custom"}:
        subscription.frequency = frequency
    subscription.days_of_week = (
        ",".join(
            sorted(
                {
                    raw
                    for raw in request.form.getlist("days_of_week")
                    if raw in {"0", "1", "2", "3", "4", "5", "6"}
                }
            )
        )
        if subscription.frequency == "custom"
        else None
    )
    next_date_raw = (request.form.get("next_scheduled_date") or "").strip()
    if next_date_raw:
        try:
            subscription.next_scheduled_date = datetime.strptime(
                next_date_raw, "%Y-%m-%d"
            ).date()
        except ValueError:
            flash("Next date was invalid, so it was left unchanged.", "warning")
    subscription.delivery_window = (
        request.form.get("delivery_window") or subscription.delivery_window or ""
    ).strip()
    subscription.notes = (request.form.get("notes") or "").strip() or None
    db.session.commit()
    flash("Recurring order updated.", "success")
    return redirect(url_for("customer.recurring_subscriptions"))


@customer_bp.route("/subscriptions/<int:subscription_id>/<action>", methods=["POST"])
@login_required
def change_recurring_subscription_status(subscription_id, action):
    subscription = RecurringSubscription.query.filter_by(
        id=subscription_id,
        user_id=current_user.id,
    ).first_or_404()
    if action == "pause":
        subscription.status = "paused"
        paused_until_raw = (request.form.get("paused_until") or "").strip()
        if paused_until_raw:
            try:
                subscription.paused_until = datetime.strptime(
                    paused_until_raw, "%Y-%m-%d"
                ).date()
            except ValueError:
                subscription.paused_until = None
        flash("Recurring order paused.", "success")
    elif action == "resume":
        subscription.status = "active"
        subscription.paused_until = None
        flash("Recurring order resumed.", "success")
    elif action == "cancel":
        subscription.status = "cancelled"
        flash("Recurring order cancelled.", "success")
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("customer.recurring_subscriptions"))


# ────────────────────────────────────────
# INVOICE
# ────────────────────────────────────────
@customer_bp.route("/orders/<int:order_id>/invoice")
@login_required
def invoice(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    items = order.items.all()
    return render_template("customer/invoice.html", order=order, items=items)
