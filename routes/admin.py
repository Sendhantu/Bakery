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
)
from flask_login import login_required, current_user
from bootstrap import get_container
from exceptions import ValidationError
from functools import wraps
from models import (
    db,
    User,
    Product,
    ProductVariant,
    Category,
    Order,
    OrderItem,
    Payment,
    Refund,
    Coupon,
    Subscription,
    Message,
    Notification,
    DeliveryAgent,
    Delivery,
    LoginHistory,
    Review,
    ModificationRequest,
    RawMaterial,
    ProductMaterial,
    Supplier,
    Branch,
    ProductionPlan,
    ProductionBatch,
    PaymentLink,
    LoyaltyLedger,
    get_loyalty_config,
    can_transition_order_status,
    get_allowed_order_statuses,
)
from services import enrich_orders
from utils import (
    parse_decimal,
    notify,
    check_and_send_inventory_alerts,
    validate_password,
)
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
from sqlalchemy import func, extract, or_
from decimal import Decimal
import os

admin_bp = Blueprint("admin", __name__)


@admin_bp.before_request
def ensure_admin_portal():
    if current_app.config.get("PORTAL_ROLE") != "admin":
        if current_user.is_authenticated and current_user.role == "admin":
            from routes.auth import portal_url_for_role

            return redirect(portal_url_for_role("admin", url_for("admin.dashboard")))
        abort(404)


# ── Auth guard ───────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def wants_live_fragment_response():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or (
        request.accept_mimetypes.best == "application/json"
    )


def sync_delivery_status(order, new_status):
    delivery = order.delivery
    if delivery is None:
        return

    new_status = (new_status or "").strip().upper()
    agent = delivery.agent

    if new_status == "DELIVERED":
        delivery.status = "DELIVERED"
        delivery.delivered_time = datetime.utcnow()
        if agent:
            agent.availability = True
        return

    delivery.delivered_time = None
    if new_status == "OUT_FOR_DELIVERY":
        delivery.status = "OUT_FOR_DELIVERY"
        if agent:
            agent.availability = False
    elif new_status == "PACKED":
        delivery.status = "PACKED"
        if agent:
            agent.availability = False
    elif new_status == "CANCELLED":
        delivery.status = "CANCELLED"
        if agent:
            agent.availability = True
    else:
        delivery.status = "ASSIGNED"
        if agent:
            agent.availability = False


@admin_bp.context_processor
def inject_admin_nav():
    """Sidebar Chat badge — must be available on every admin page (base_admin.html)."""
    from flask_login import current_user as cu

    if not cu.is_authenticated or cu.role != "admin":
        return {"pending_msgs": 0}
    count = Message.query.filter_by(receiver_id=cu.id, is_read=False).count()
    return {"pending_msgs": count}


# ── Image helper ─────────────────────────────────────────────
def apply_product_image(product):
    from flask import current_app
    from werkzeug.utils import secure_filename

    allowed = current_app.config.get(
        "ALLOWED_IMAGE_EXTENSIONS", {"jpg", "jpeg", "png", "webp", "gif"}
    )

    image_url = (request.form.get("image_url") or "").strip()
    if image_url.startswith(("http://", "https://")):
        product.image = image_url

    if "image" in request.files and request.files["image"].filename:
        f = request.files["image"]
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in allowed:
            flash(f'Invalid image type .{ext}. Allowed: {", ".join(allowed)}', "danger")
            return
        filename = secure_filename(f.filename)
        f.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
        product.image = filename


# ── Recipe sync ──────────────────────────────────────────────
def sync_product_materials(product):
    material_ids = request.form.getlist("recipe_material_id[]")
    quantities = request.form.getlist("recipe_quantity[]")
    submitted_ids = set()

    for mat_id, qty in zip(material_ids, quantities):
        if not mat_id:
            continue
        mat = RawMaterial.query.get(int(mat_id))
        if not mat:
            continue
        try:
            qty_dec = parse_decimal(qty, f"{mat.name} quantity")
        except ValueError:
            continue
        if qty_dec <= 0:
            continue
        submitted_ids.add(mat.id)
        existing = ProductMaterial.query.filter_by(
            product_id=product.id, raw_material_id=mat.id
        ).first()
        if existing:
            existing.quantity_required = qty_dec
        else:
            db.session.add(
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=mat.id,
                    quantity_required=qty_dec,
                )
            )

    for req in product.recipe_items.all():
        if req.raw_material_id not in submitted_ids:
            db.session.delete(req)


def build_order_payment_link(order):
    return PaymentLink.create_pending(
        user_id=order.user_id,
        order_id=order.id,
        purpose="ORDER",
        title=f"Payment for Order #{order.order_number}",
        amount=order.total,
        payment_method=order.payment_method,
        success_url=url_for("customer.order_detail", order_id=order.id),
        cancel_url=url_for("admin.order_detail", order_id=order.id),
        notes="Placeholder payment page for future gateway integration.",
    )


# ── DASHBOARD ────────────────────────────────────────────────
@admin_bp.route("/")
@admin_required
def dashboard():
    today = datetime.utcnow().date()

    total_orders = Order.query.count()
    today_orders = Order.query.filter(func.date(Order.placed_at) == today).count()
    total_revenue = (
        db.session.query(func.sum(Order.total))
        .filter(Order.status != "CANCELLED")
        .scalar()
        or 0
    )
    today_revenue = (
        db.session.query(func.sum(Order.total))
        .filter(func.date(Order.placed_at) == today, Order.status != "CANCELLED")
        .scalar()
        or 0
    )
    total_customers = User.query.filter_by(role="customer").count()
    pending_orders = Order.query.filter(
        Order.status.in_(["PLACED", "PREPARING"])
    ).count()
    low_stock_items = ProductVariant.query.filter(
        ProductVariant.stock <= 5, ProductVariant.stock > 0
    ).count()
    out_of_stock = ProductVariant.query.filter_by(stock=0).count()
    inactive_products = Product.query.filter_by(is_active=False).count()
    low_stock_materials = RawMaterial.query.filter(
        RawMaterial.is_active == True,
        RawMaterial.stock > 0,
        RawMaterial.stock <= RawMaterial.reorder_level,
    ).count()
    out_of_stock_materials = RawMaterial.query.filter(
        RawMaterial.is_active == True, RawMaterial.stock <= 0
    ).count()
    total_loyalty_points = (
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0)).scalar() or 0
    )

    recent_orders = Order.query.order_by(Order.placed_at.desc()).limit(8).all()
    enrich_orders(recent_orders)

    # Compare with previous 7-day window for quick trend badges
    window_start = today - timedelta(days=6)
    prev_window_start = today - timedelta(days=13)
    prev_window_end = today - timedelta(days=7)

    current_week_orders = Order.query.filter(
        func.date(Order.placed_at) >= window_start,
        func.date(Order.placed_at) <= today,
    ).count()
    prev_week_orders = Order.query.filter(
        func.date(Order.placed_at) >= prev_window_start,
        func.date(Order.placed_at) <= prev_window_end,
    ).count()

    current_week_revenue = (
        db.session.query(func.sum(Order.total))
        .filter(
            func.date(Order.placed_at) >= window_start,
            func.date(Order.placed_at) <= today,
            Order.status != "CANCELLED",
        )
        .scalar()
        or 0
    )
    prev_week_revenue = (
        db.session.query(func.sum(Order.total))
        .filter(
            func.date(Order.placed_at) >= prev_window_start,
            func.date(Order.placed_at) <= prev_window_end,
            Order.status != "CANCELLED",
        )
        .scalar()
        or 0
    )

    current_week_new_customers = User.query.filter(
        User.role == "customer",
        func.date(User.created_at) >= window_start,
        func.date(User.created_at) <= today,
    ).count()
    prev_week_new_customers = User.query.filter(
        User.role == "customer",
        func.date(User.created_at) >= prev_window_start,
        func.date(User.created_at) <= prev_window_end,
    ).count()

    def trend(current, previous):
        if previous == 0:
            if current == 0:
                return {"pct": 0, "dir": "flat"}
            return {"pct": 100, "dir": "up"}
        pct = round(((float(current) - float(previous)) / float(previous)) * 100, 1)
        if pct > 0:
            direction = "up"
        elif pct < 0:
            direction = "down"
        else:
            direction = "flat"
        return {"pct": abs(pct), "dir": direction}

    trend_revenue = trend(current_week_revenue, prev_week_revenue)
    trend_orders = trend(current_week_orders, prev_week_orders)
    trend_customers = trend(current_week_new_customers, prev_week_new_customers)

    labels, revenues, order_counts = [], [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%b %d"))
        rev = (
            db.session.query(func.sum(Order.total))
            .filter(func.date(Order.placed_at) == d, Order.status != "CANCELLED")
            .scalar()
            or 0
        )
        cnt = Order.query.filter(func.date(Order.placed_at) == d).count()
        revenues.append(float(rev))
        order_counts.append(cnt)

    top_products = (
        db.session.query(Product.name, func.sum(OrderItem.quantity).label("sold"))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    pending_msgs = Message.query.filter_by(
        receiver_id=current_user.id, is_read=False
    ).count()
    mod_requests = ModificationRequest.query.filter_by(status="PENDING").count()
    branch_count = Branch.query.count()
    supplier_count = Supplier.query.count()
    supplier_alerts = Supplier.query.filter_by(is_active=False).count()

    context = dict(
        total_orders=total_orders,
        today_orders=today_orders,
        total_revenue=total_revenue,
        today_revenue=today_revenue,
        total_customers=total_customers,
        pending_orders=pending_orders,
        low_stock_items=low_stock_items,
        out_of_stock=out_of_stock,
        inactive_products=inactive_products,
        low_stock_materials=low_stock_materials,
        out_of_stock_materials=out_of_stock_materials,
        material_alerts=low_stock_materials + out_of_stock_materials,
        branch_count=branch_count,
        supplier_count=supplier_count,
        supplier_alerts=supplier_alerts,
        total_loyalty_points=int(total_loyalty_points),
        recent_orders=recent_orders,
        chart_labels=labels,
        chart_revenues=revenues,
        chart_order_counts=order_counts,
        top_products=top_products,
        pending_msgs=pending_msgs,
        mod_requests=mod_requests,
        trend_revenue=trend_revenue,
        trend_orders=trend_orders,
        trend_customers=trend_customers,
        current_date_label=today.strftime("%A, %d %B %Y"),
    )
    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-dashboard-live": render_template(
                        "admin/_dashboard_live.html", **context
                    )
                }
            }
        )
    return render_template("admin/dashboard.html", **context)


# ── PRODUCT MANAGEMENT ───────────────────────────────────────
@admin_bp.route("/products")
@admin_required
def products():
    search = (request.args.get("q") or "").strip()
    get_container().inventory_service.backfill_missing_product_variants()
    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    products = query.order_by(
        Product.is_active.desc(), Product.created_at.desc()
    ).all()
    return render_template("admin/products.html", products=products, search=search)


@admin_bp.route("/products/add", methods=["GET", "POST"])
@admin_required
def add_product():
    categories = Category.query.all()
    raw_materials = (
        RawMaterial.query.filter_by(is_active=True).order_by(RawMaterial.name).all()
    )
    if request.method == "POST":
        p = Product(
            name=request.form["name"],
            description=request.form.get("description"),
            ingredients=request.form.get("ingredients"),
            preparation=request.form.get("preparation"),
            base_price=request.form["base_price"],
            category_id=request.form.get("category_id", type=int),
            is_eggless=bool(request.form.get("is_eggless")),
            is_featured=bool(request.form.get("is_featured")),
            preorder_required=bool(request.form.get("preorder_required")),
            minimum_notice_hours=max(1, request.form.get("minimum_notice_hours", type=int) or 24),
            occasion_tags=request.form.get("occasion_tags", ""),
        )
        apply_product_image(p)
        db.session.add(p)
        db.session.flush()
        variant_rows = [
            {"id": None, "name": vn, "price": vp, "stock": vs}
            for vn, vp, vs in zip(
                request.form.getlist("variant_name[]"),
                request.form.getlist("variant_price[]"),
                request.form.getlist("variant_stock[]"),
            )
        ]
        try:
            get_container().inventory_service.sync_product_variants(p, variant_rows)
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "admin/product_form.html",
                product=None,
                categories=categories,
                raw_materials=raw_materials,
            )
        sync_product_materials(p)
        db.session.commit()
        flash("Product added!", "success")
        return redirect(url_for("admin.products"))
    return render_template(
        "admin/product_form.html",
        product=None,
        categories=categories,
        raw_materials=raw_materials,
    )


@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    p = Product.query.get_or_404(product_id)
    categories = Category.query.all()
    raw_materials = (
        RawMaterial.query.filter_by(is_active=True).order_by(RawMaterial.name).all()
    )
    if request.method == "POST":
        p.name = request.form["name"]
        p.description = request.form.get("description")
        p.ingredients = request.form.get("ingredients")
        p.preparation = request.form.get("preparation")
        p.base_price = request.form["base_price"]
        p.category_id = request.form.get("category_id", type=int)
        p.is_eggless = bool(request.form.get("is_eggless"))
        p.is_featured = bool(request.form.get("is_featured"))
        p.is_active = bool(request.form.get("is_active"))
        p.preorder_required = bool(request.form.get("preorder_required"))
        p.minimum_notice_hours = max(1, request.form.get("minimum_notice_hours", type=int) or 24)
        p.occasion_tags = request.form.get("occasion_tags", "")
        apply_product_image(p)
        variant_rows = [
            {"id": vid, "name": vn, "price": vp, "stock": vs}
            for vid, vn, vp, vs in zip(
                request.form.getlist("variant_id[]"),
                request.form.getlist("variant_name[]"),
                request.form.getlist("variant_price[]"),
                request.form.getlist("variant_stock[]"),
            )
        ]
        try:
            get_container().inventory_service.sync_product_variants(p, variant_rows)
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "admin/product_form.html",
                product=p,
                categories=categories,
                raw_materials=raw_materials,
            )

        sync_product_materials(p)
        db.session.commit()
        flash("Product updated!", "success")
        return redirect(url_for("admin.products"))
    return render_template(
        "admin/product_form.html",
        product=p,
        categories=categories,
        raw_materials=raw_materials,
    )


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def delete_product(product_id):
    p = Product.query.get_or_404(product_id)
    if p.is_active:
        p.is_active = False
        db.session.commit()
        flash("Product moved offline.", "info")
        return redirect(url_for("admin.products"))
    if p.total_stock <= 0:
        flash(
            "Add stock to at least one variant before making this product live.",
            "warning",
        )
        return redirect(url_for("admin.inventory"))
    p.is_active = True
    db.session.commit()
    flash("Product is live again.", "success")
    return redirect(url_for("admin.products"))


# ── ORDER MANAGEMENT ─────────────────────────────────────────
@admin_bp.route("/orders")
@admin_required
def orders():
    status = request.args.get("status", "")
    scope = request.args.get("scope", "")
    search = (request.args.get("q") or "").strip()
    query = Order.query.join(User, Order.user_id == User.id)
    if status:
        query = query.filter(Order.status == status)
    if scope == "today":
        query = query.filter(func.date(Order.placed_at) == datetime.utcnow().date())
    elif scope == "pending":
        query = query.filter(Order.status.in_(["PLACED", "PREPARING"]))
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Order.order_number.ilike(like),
                Order.phone.ilike(like),
                User.name.ilike(like),
                User.email.ilike(like),
            )
        )
    orders = query.order_by(Order.placed_at.desc()).all()
    enrich_orders(orders)
    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-orders-live": render_template(
                        "admin/_orders_live.html",
                        orders=orders,
                    )
                }
            }
        )
    return render_template(
        "admin/orders.html",
        orders=orders,
        status_filter=status,
        scope_filter=scope,
        search=search,
    )


@admin_bp.route("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    items = order.items.all()
    agents = DeliveryAgent.query.order_by(
        DeliveryAgent.availability.desc(), DeliveryAgent.name
    ).all()
    mod_reqs = order.mod_requests.all()
    addr_hist = order.addr_history.all()
    payment_link = (
        PaymentLink.query.filter_by(
            order_id=order.id, purpose="ORDER", status="PENDING"
        )
        .order_by(PaymentLink.id.desc())
        .first()
    )
    return render_template(
        "admin/order_detail.html",
        order=order,
        items=items,
        agents=agents,
        mod_reqs=mod_reqs,
        addr_hist=addr_hist,
        payment_link=payment_link,
        allowed_statuses=get_allowed_order_statuses(order.status, actor="admin"),
    )


@admin_bp.route("/orders/<int:order_id>/update-status", methods=["POST"])
@admin_required
def update_order_status(order_id):
    status = (request.form.get("status") or "").strip().upper()
    try:
        order = get_container().order_service.update_order_status(
            order_id,
            status,
            actor="admin",
        )
    except ValueError:
        flash("Please choose a valid status.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    except ValidationError as exc:
        message = str(exc) or "That status change is not allowed right now."
        flash(message, "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    flash(f"Order status updated to {status}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.route("/orders/<int:order_id>/assign-delivery", methods=["POST"])
@admin_required
def assign_delivery(order_id):
    order = Order.query.get_or_404(order_id)
    agent_id = request.form.get("agent_id", type=int)
    agent = DeliveryAgent.query.get_or_404(agent_id)

    existing = Delivery.query.filter_by(order_id=order_id).first()
    if existing:
        existing.agent_id = agent_id
        existing.assigned_time = datetime.utcnow()
    else:
        db.session.add(
            Delivery(
                order_id=order_id, agent_id=agent_id, assigned_time=datetime.utcnow()
            )
        )
    agent.availability = False
    db.session.commit()
    flash(f"Delivery assigned to {agent.name}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.route("/orders/<int:order_id>/payment-link")
@admin_required
def order_payment_link(order_id):
    order = Order.query.get_or_404(order_id)
    link = build_order_payment_link(order)
    db.session.commit()
    flash("Payment page ready.", "info")
    return redirect(url_for("customer.payment_link_page", token=link.token))


# ── MODIFICATION REQUESTS ────────────────────────────────────
@admin_bp.route("/modifications")
@admin_required
def modifications():
    reqs = (
        ModificationRequest.query.filter_by(status="PENDING")
        .order_by(ModificationRequest.created_at.desc())
        .all()
    )
    return render_template("admin/modifications.html", reqs=reqs)


@admin_bp.route("/modifications/<int:req_id>/resolve", methods=["POST"])
@admin_required
def resolve_modification(req_id):
    req = ModificationRequest.query.get_or_404(req_id)
    action = request.form.get("action")
    req.status = "APPROVED" if action == "approve" else "REJECTED"
    req.resolved_at = datetime.utcnow()
    req.order.is_locked = False

    if action == "approve":
        try:
            price_diff = float(request.form.get("price_diff", 0) or 0)
        except ValueError:
            price_diff = 0
        if price_diff > 0:
            req.order.status = "ON_HOLD"
            req.order.total += Decimal(str(price_diff))
            notify(
                req.order.user_id,
                "Extra Payment Required",
                f"Your modified order #{req.order.order_number} requires ₹{price_diff:.0f} extra.",
                "payment",
            )
        elif price_diff < 0:
            req.order.total += Decimal(str(price_diff))
            db.session.add(
                Refund(
                    order_id=req.order.id,
                    amount=abs(price_diff),
                    reason="Order modification – price reduced",
                    status="PROCESSING",
                )
            )
    db.session.commit()
    flash("Modification request resolved.", "success")
    return redirect(url_for("admin.modifications"))


# ── CUSTOMERS ────────────────────────────────────────────────
@admin_bp.route("/customers")
@admin_required
def customers():
    users = User.query.filter_by(role="customer").order_by(User.created_at.desc()).all()
    return render_template("admin/customers.html", users=users)


@admin_bp.route("/customers/<int:user_id>")
@admin_required
def customer_detail(user_id):
    user = User.query.get_or_404(user_id)
    orders = (
        Order.query.filter_by(user_id=user_id).order_by(Order.placed_at.desc()).all()
    )
    logins = (
        LoginHistory.query.filter_by(user_id=user_id)
        .order_by(LoginHistory.login_time.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "admin/customer_detail.html", user=user, orders=orders, logins=logins
    )


# ── CHAT ─────────────────────────────────────────────────────
@admin_bp.route("/chat")
@admin_required
def chat():
    customers = (
        db.session.query(User)
        .join(Message, Message.sender_id == User.id)
        .filter(Message.receiver_id == current_user.id)
        .distinct()
        .all()
    )
    return render_template("admin/chat.html", customers=customers)


@admin_bp.route("/chat/<int:customer_id>")
@admin_required
def chat_thread(customer_id):
    customer = User.query.get_or_404(customer_id)
    messages = (
        Message.query.filter(
            (
                (Message.sender_id == current_user.id)
                & (Message.receiver_id == customer_id)
            )
            | (
                (Message.sender_id == customer_id)
                & (Message.receiver_id == current_user.id)
            )
        )
        .order_by(Message.sent_at.asc())
        .all()
    )
    Message.query.filter_by(
        receiver_id=current_user.id, sender_id=customer_id, is_read=False
    ).update({"is_read": True})
    db.session.commit()
    customers = (
        db.session.query(User)
        .join(Message, Message.sender_id == User.id)
        .filter(Message.receiver_id == current_user.id)
        .distinct()
        .all()
    )
    return render_template(
        "admin/chat.html",
        customers=customers,
        messages=messages,
        active_customer=customer,
    )


@admin_bp.route("/chat/send/<int:receiver_id>", methods=["POST"])
@admin_required
def admin_send_message(receiver_id):
    content = request.form.get("content", "").strip()
    if content:
        db.session.add(
            Message(sender_id=current_user.id, receiver_id=receiver_id, content=content)
        )
        notify(
            receiver_id,
            "New Message from Bakery",
            content[:100],
            "chat",
            url_for("customer.chat"),
        )
        db.session.commit()
    return redirect(url_for("admin.chat_thread", customer_id=receiver_id))


# ── INVENTORY ────────────────────────────────────────────────
@admin_bp.route("/inventory")
@admin_required
def inventory():
    get_container().inventory_service.backfill_missing_product_variants()
    variants = (
        ProductVariant.query.join(Product)
        .order_by(Product.is_active.desc(), ProductVariant.stock.asc(), Product.name)
        .all()
    )
    materials = RawMaterial.query.order_by(
        RawMaterial.is_active.desc(), RawMaterial.stock.asc(), RawMaterial.name
    ).all()
    live_products = Product.query.filter_by(is_active=True).count()
    inactive_products = Product.query.filter_by(is_active=False).count()
    low_variant_count = ProductVariant.query.filter(
        ProductVariant.stock > 0, ProductVariant.stock <= 5
    ).count()
    out_of_stock_count = ProductVariant.query.filter_by(stock=0).count()
    raw_material_alerts = RawMaterial.query.filter(
        RawMaterial.is_active == True, RawMaterial.stock <= RawMaterial.reorder_level
    ).count()
    return render_template(
        "admin/inventory.html",
        variants=variants,
        materials=materials,
        live_products=live_products,
        inactive_products=inactive_products,
        low_variant_count=low_variant_count,
        out_of_stock_count=out_of_stock_count,
        raw_material_alerts=raw_material_alerts,
    )


@admin_bp.route("/inventory/update", methods=["POST"])
@admin_required
def update_stock():
    v = ProductVariant.query.get_or_404(request.form.get("variant_id", type=int))
    v.stock = request.form.get("stock", type=int)
    db.session.commit()
    # Trigger inventory email alert if stock is low
    try:
        check_and_send_inventory_alerts()
    except Exception:
        pass
    flash("Stock updated!", "success")
    return redirect(url_for("admin.inventory"))


@admin_bp.route("/inventory/raw-material/update", methods=["POST"])
@admin_required
def update_raw_material_stock():
    mat = RawMaterial.query.get_or_404(request.form.get("material_id", type=int))
    try:
        mat.stock = parse_decimal(request.form.get("stock"), "stock")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.inventory"))
    db.session.commit()
    try:
        check_and_send_inventory_alerts()
    except Exception:
        pass
    flash("Raw material stock updated!", "success")
    return redirect(url_for("admin.inventory"))


@admin_bp.route("/suppliers")
@admin_required
def suppliers():
    search = (request.args.get("q") or "").strip()
    query = Supplier.query
    if search:
        query = query.filter(Supplier.name.ilike(f"%{search}%"))
    suppliers = query.order_by(Supplier.is_active.desc(), Supplier.name).all()
    return render_template("admin/suppliers.html", suppliers=suppliers, search=search)


@admin_bp.route("/suppliers/add", methods=["POST"])
@admin_required
def add_supplier():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Supplier name is required.", "danger")
        return redirect(url_for("admin.suppliers"))
    if Supplier.query.filter(func.lower(Supplier.name) == name.lower()).first():
        flash("Supplier already exists.", "warning")
        return redirect(url_for("admin.suppliers"))
    supplier = Supplier(
        name=name,
        contact_name=(request.form.get("contact_name") or "").strip(),
        email=(request.form.get("email") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        address=(request.form.get("address") or "").strip(),
        payment_terms=(request.form.get("payment_terms") or "").strip(),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(supplier)
    db.session.commit()
    flash("Supplier added successfully.", "success")
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/suppliers/<int:supplier_id>/toggle", methods=["POST"])
@admin_required
def toggle_supplier_status(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    supplier.is_active = not supplier.is_active
    db.session.commit()
    flash(
        f"Supplier {'activated' if supplier.is_active else 'paused'}.",
        "success" if supplier.is_active else "info",
    )
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/branches")
@admin_required
def branches():
    branches = Branch.query.order_by(Branch.is_active.desc(), Branch.name).all()
    return render_template("admin/branches.html", branches=branches)


@admin_bp.route("/branches/add", methods=["POST"])
@admin_required
def add_branch():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Branch name is required.", "danger")
        return redirect(url_for("admin.branches"))
    if Branch.query.filter(func.lower(Branch.name) == name.lower()).first():
        flash("Branch already exists.", "warning")
        return redirect(url_for("admin.branches"))
    branch = Branch(
        name=name,
        manager_name=(request.form.get("manager_name") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        address=(request.form.get("address") or "").strip(),
    )
    db.session.add(branch)
    db.session.commit()
    flash("Branch added successfully.", "success")
    return redirect(url_for("admin.branches"))


@admin_bp.route("/branches/<int:branch_id>/toggle", methods=["POST"])
@admin_required
def toggle_branch_status(branch_id):
    branch = Branch.query.get_or_404(branch_id)
    branch.is_active = not branch.is_active
    db.session.commit()
    flash(
        f"Branch {'opened' if branch.is_active else 'closed'}.",
        "success" if branch.is_active else "warning",
    )
    return redirect(url_for("admin.branches"))


@admin_bp.route("/production")
@admin_required
def production():
    plans = ProductionPlan.query.order_by(ProductionPlan.planned_date.desc()).all()
    batches = ProductionBatch.query.order_by(ProductionBatch.produced_at.desc()).limit(25).all()
    products = Product.query.order_by(Product.name).all()
    branches = Branch.query.order_by(Branch.name).all()
    return render_template(
        "admin/production.html",
        plans=plans,
        batches=batches,
        products=products,
        branches=branches,
    )


@admin_bp.route("/production/add", methods=["POST"])
@admin_required
def add_production_plan():
    product_id = request.form.get("product_id", type=int)
    planned_date = request.form.get("planned_date")
    quantity = request.form.get("quantity", type=int)
    branch_id = request.form.get("branch_id", type=int)
    if not product_id or not planned_date or quantity is None:
        flash("Product, date, and quantity are required.", "danger")
        return redirect(url_for("admin.production"))
    try:
        planned_date = datetime.strptime(planned_date, "%Y-%m-%d")
    except ValueError:
        flash("Invalid production date.", "danger")
        return redirect(url_for("admin.production"))
    plan = ProductionPlan(
        product_id=product_id,
        branch_id=branch_id if branch_id else None,
        planned_date=planned_date,
        quantity=quantity,
        status=request.form.get("status", "Scheduled"),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(plan)
    db.session.commit()
    flash("Production plan created.", "success")
    return redirect(url_for("admin.production"))


@admin_bp.route("/batches")
@admin_required
def batches():
    batches = ProductionBatch.query.order_by(ProductionBatch.produced_at.desc()).all()
    products = Product.query.order_by(Product.name).all()
    branches = Branch.query.order_by(Branch.name).all()
    return render_template("admin/batches.html", batches=batches, products=products, branches=branches)


@admin_bp.route("/batches/add", methods=["POST"])
@admin_required
def add_batch():
    product_id = request.form.get("product_id", type=int)
    branch_id = request.form.get("branch_id", type=int)
    produced_at = request.form.get("produced_at")
    expiry_date = request.form.get("expiry_date")
    quantity = request.form.get("quantity", type=int)
    waste_percentage = request.form.get("waste_percentage", type=float) or 0
    if not product_id or not produced_at or quantity is None:
        flash("Product, production date, and quantity are required.", "danger")
        return redirect(url_for("admin.batches"))
    try:
        produced_at = datetime.strptime(produced_at, "%Y-%m-%d")
    except ValueError:
        flash("Invalid production date.", "danger")
        return redirect(url_for("admin.batches"))
    expiry_dt = None
    if expiry_date:
        try:
            expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            flash("Invalid expiry date.", "danger")
            return redirect(url_for("admin.batches"))
    batch = ProductionBatch(
        product_id=product_id,
        branch_id=branch_id if branch_id else None,
        produced_at=produced_at,
        expiry_date=expiry_dt,
        quantity=quantity,
        waste_percentage=waste_percentage,
        status=request.form.get("status", "Produced"),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(batch)
    db.session.commit()
    flash("Production batch logged.", "success")
    return redirect(url_for("admin.batches"))


@admin_bp.route("/batches/<int:batch_id>/update", methods=["POST"])
@admin_required
def update_batch(batch_id):
    batch = ProductionBatch.query.get_or_404(batch_id)
    batch.status = request.form.get("status", batch.status)
    batch.notes = (request.form.get("notes") or "").strip()
    try:
        batch.waste_percentage = float(request.form.get("waste_percentage", batch.waste_percentage) or 0)
    except ValueError:
        flash("Invalid waste percentage.", "danger")
        return redirect(url_for("admin.batches"))
    db.session.commit()
    flash("Batch updated.", "success")
    return redirect(url_for("admin.batches"))


@admin_bp.route("/raw-materials")
@admin_required
def raw_materials():
    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", 12, type=int) or 12
    per_page = max(1, min(per_page, 50))

    query = RawMaterial.query
    if search:
        query = query.filter(RawMaterial.name.ilike(f"%{search}%"))
    pagination = query.order_by(
        RawMaterial.is_active.desc(), RawMaterial.name.asc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    materials = pagination.items
    low_stock_count = RawMaterial.query.filter(
        RawMaterial.is_active == True,
        RawMaterial.stock > 0,
        RawMaterial.stock <= RawMaterial.reorder_level,
    ).count()
    out_of_stock_count = RawMaterial.query.filter(
        RawMaterial.is_active == True, RawMaterial.stock <= 0
    ).count()
    return render_template(
        "admin/raw_materials.html",
        materials=materials,
        pagination=pagination,
        search=search,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count,
    )


@admin_bp.route("/raw-materials/add", methods=["POST"])
@admin_required
def add_raw_material():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Material name is required.", "danger")
        return redirect(url_for("admin.raw_materials"))
    if RawMaterial.query.filter(func.lower(RawMaterial.name) == name.lower()).first():
        flash("A material with that name already exists.", "warning")
        return redirect(url_for("admin.raw_materials"))
    try:
        stock = parse_decimal(request.form.get("stock"), "stock")
        reorder = parse_decimal(request.form.get("reorder_level"), "reorder level")
        cost = parse_decimal(request.form.get("cost_per_unit"), "cost per unit")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.raw_materials"))
    db.session.add(
        RawMaterial(
            name=name,
            unit=request.form.get("unit", "").strip() or "kg",
            stock=stock,
            reorder_level=reorder,
            cost_per_unit=cost,
            supplier=request.form.get("supplier", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
        )
    )
    db.session.commit()
    flash("Raw material added.", "success")
    return redirect(url_for("admin.raw_materials"))


@admin_bp.route("/raw-materials/<int:material_id>/update", methods=["POST"])
@admin_required
def update_raw_material(material_id):
    mat = RawMaterial.query.get_or_404(material_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("admin.raw_materials"))
    dup = RawMaterial.query.filter(
        func.lower(RawMaterial.name) == name.lower(), RawMaterial.id != mat.id
    ).first()
    if dup:
        flash("Another material already uses that name.", "warning")
        return redirect(url_for("admin.raw_materials"))
    try:
        mat.stock = parse_decimal(request.form.get("stock"), "stock")
        mat.reorder_level = parse_decimal(
            request.form.get("reorder_level"), "reorder level"
        )
        mat.cost_per_unit = parse_decimal(
            request.form.get("cost_per_unit"), "cost per unit"
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.raw_materials"))
    mat.name = name
    mat.unit = request.form.get("unit", "").strip() or "kg"
    mat.supplier = request.form.get("supplier", "").strip() or None
    mat.notes = request.form.get("notes", "").strip() or None
    db.session.commit()
    try:
        check_and_send_inventory_alerts()
    except Exception:
        pass
    flash("Raw material updated.", "success")
    return redirect(url_for("admin.raw_materials"))


@admin_bp.route("/raw-materials/<int:material_id>/toggle", methods=["POST"])
@admin_required
def toggle_raw_material_status(material_id):
    mat = RawMaterial.query.get_or_404(material_id)
    mat.is_active = not mat.is_active
    db.session.commit()
    flash(
        "Raw material " + ("enabled." if mat.is_active else "paused."),
        "success" if mat.is_active else "info",
    )
    return redirect(url_for("admin.raw_materials"))


# ── COUPONS ──────────────────────────────────────────────────
@admin_bp.route("/coupons")
@admin_required
def coupons():
    search = (request.args.get("q") or "").strip()
    query = Coupon.query
    if search:
        query = query.filter(Coupon.code.ilike(f"%{search}%"))
    coupons = query.order_by(Coupon.id.desc()).all()
    for coupon in coupons:
        coupon.is_currently_valid = coupon.is_valid()
    return render_template("admin/coupons.html", coupons=coupons, search=search)


@admin_bp.route("/coupons/add", methods=["POST"])
@admin_required
def add_coupon():
    code = request.form.get("code", "").strip().upper()
    if not code:
        flash("Coupon code is required.", "danger")
        return redirect(url_for("admin.coupons"))
    if Coupon.query.filter_by(code=code).first():
        flash("Coupon code already exists.", "warning")
        return redirect(url_for("admin.coupons"))
    try:
        discount_value = parse_decimal(
            request.form.get("discount_value"), "discount value"
        )
        min_order_value = parse_decimal(
            request.form.get("min_order_value"), "min order value"
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.coupons"))
    valid_until = None
    if request.form.get("valid_until"):
        try:
            valid_until = datetime.strptime(request.form["valid_until"], "%Y-%m-%d")
        except ValueError:
            flash("Invalid expiry date.", "danger")
            return redirect(url_for("admin.coupons"))
    db.session.add(
        Coupon(
            code=code,
            discount_type=request.form.get("discount_type", "percentage"),
            discount_value=discount_value,
            min_order_value=min_order_value,
            max_uses=int(request.form.get("max_uses") or 100),
            valid_until=valid_until,
        )
    )
    db.session.commit()
    flash("Coupon created!", "success")
    return redirect(url_for("admin.coupons"))


@admin_bp.route("/coupons/<int:coupon_id>/toggle", methods=["POST"])
@admin_required
def toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    flash(
        f"Coupon {'enabled' if coupon.is_active else 'paused'}.",
        "success" if coupon.is_active else "info",
    )
    search = (request.args.get("q") or "").strip()
    return redirect(url_for("admin.coupons", q=search) if search else url_for("admin.coupons"))


# ── DELIVERY AGENTS ──────────────────────────────────────────
@admin_bp.route("/agents")
@admin_required
def agents():
    agents = (
        DeliveryAgent.query.outerjoin(User, DeliveryAgent.user_id == User.id)
        .order_by(
            User.is_active.desc(),
            DeliveryAgent.availability.desc(),
            DeliveryAgent.name.asc(),
        )
        .all()
    )

    active_agents = 0
    busy_agents = 0
    inactive_agents = 0

    for agent in agents:
        open_deliveries = agent.deliveries.filter(
            Delivery.status != "DELIVERED"
        ).count()
        completed_deliveries = agent.deliveries.filter(
            Delivery.status == "DELIVERED"
        ).count()
        agent.open_delivery_count = open_deliveries
        agent.completed_delivery_count = completed_deliveries

        if agent.user and agent.user.is_active:
            active_agents += 1
            if not agent.availability or open_deliveries:
                busy_agents += 1
        else:
            inactive_agents += 1

    stats = {
        "total": len(agents),
        "active": active_agents,
        "busy": busy_agents,
        "inactive": inactive_agents,
    }
    return render_template("admin/agents.html", agents=agents, stats=stats)


@admin_bp.route("/agents/add", methods=["POST"])
@admin_required
def add_agent():
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    if len(name) < 2:
        flash("Agent name must be at least 2 characters.", "danger")
        return redirect(url_for("admin.agents"))
    if not phone:
        flash("Phone number is required.", "danger")
        return redirect(url_for("admin.agents"))
    if not email:
        flash("Email is required.", "danger")
        return redirect(url_for("admin.agents"))
    password_errors = validate_password(password)
    if password_errors:
        for err in password_errors:
            flash(err, "danger")
        return redirect(url_for("admin.agents"))
    if User.query.filter_by(email=email).first():
        flash("That email is already in use.", "danger")
        return redirect(url_for("admin.agents"))

    user = User(name=name, email=email, phone=phone, role="delivery", is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    db.session.add(
        DeliveryAgent(
            user_id=user.id,
            name=name,
            phone=phone,
            availability=True,
        )
    )
    db.session.commit()
    from app import record_development_credential

    record_development_credential(
        "delivery",
        email,
        password,
        label=f"Delivery Account ({name})",
        source="admin_created",
    )
    if current_app.config.get("SHOW_DEMO_ACCOUNTS", False):
        flash(
            f"Delivery account created for {name}. Credentials: {email} / {password}",
            "success",
        )
        current_app.logger.info(
            "Delivery credentials created: %s / %s", email, password
        )
    else:
        flash(f"Delivery account created for {name}.", "success")
        current_app.logger.info("Delivery account created: %s", email)
    return redirect(url_for("admin.agents"))


@admin_bp.route("/agents/<int:agent_id>/reset-password", methods=["POST"])
@admin_required
def reset_agent_password(agent_id):
    agent = DeliveryAgent.query.get_or_404(agent_id)
    if agent.user is None:
        flash("This delivery profile is not linked to a login account yet.", "danger")
        return redirect(url_for("admin.agents"))

    password = (request.form.get("password") or "").strip()
    password_errors = validate_password(password)
    if password_errors:
        for err in password_errors:
            flash(err, "danger")
        return redirect(url_for("admin.agents"))

    agent.user.set_password(password)
    agent.user.is_active = True
    db.session.commit()

    from app import record_development_credential

    record_development_credential(
        "delivery",
        agent.user.email,
        password,
        label=f"Delivery Account ({agent.name})",
        source="admin_reset",
    )
    if current_app.config.get("SHOW_DEMO_ACCOUNTS", False):
        flash(
            f"Password reset for {agent.name}. Credentials: {agent.user.email} / {password}",
            "success",
        )
        current_app.logger.info(
            "Delivery credentials reset: %s / %s", agent.user.email, password
        )
    else:
        flash(f"Password reset for {agent.name}.", "success")
        current_app.logger.info("Delivery password reset: %s", agent.user.email)
    return redirect(url_for("admin.agents"))


@admin_bp.route("/agents/<int:agent_id>/toggle-access", methods=["POST"])
@admin_required
def toggle_agent_access(agent_id):
    agent = DeliveryAgent.query.get_or_404(agent_id)
    if agent.user is None:
        flash("This delivery profile is not linked to a login account yet.", "danger")
        return redirect(url_for("admin.agents"))

    agent.user.is_active = not agent.user.is_active
    if not agent.user.is_active:
        agent.availability = False
        flash(f"{agent.name} has been deactivated.", "warning")
    else:
        has_open_delivery = (
            agent.deliveries.filter(Delivery.status != "DELIVERED").first() is not None
        )
        agent.availability = not has_open_delivery
        flash(f"{agent.name} has been reactivated.", "success")

    db.session.commit()
    return redirect(url_for("admin.agents"))


# ── ANALYTICS ────────────────────────────────────────────────
@admin_bp.route("/analytics")
@admin_required
def analytics():
    today = datetime.utcnow().date()

    # ── Monthly revenue — FIXED: uses dateutil.relativedelta for accurate months ──
    monthly_data = []
    try:
        for i in range(5, -1, -1):
            month_start = today.replace(day=1) - relativedelta(months=i)
            next_month = month_start + relativedelta(months=1)
            rev = (
                db.session.query(func.sum(Order.total))
                .filter(
                    Order.placed_at >= month_start,
                    Order.placed_at < next_month,
                    Order.status != "CANCELLED",
                )
                .scalar()
                or 0
            )
            monthly_data.append(
                {"month": month_start.strftime("%b %Y"), "revenue": float(rev)}
            )
    except Exception:
        # Fallback if dateutil not installed
        monthly_data = [{"month": "N/A", "revenue": 0}]

    # ── Order status breakdown ──
    status_rows = (
        db.session.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    status_counts = {s: c for s, c in status_rows}

    # ── Top products ──
    top_products = (
        db.session.query(
            Product.name,
            func.sum(OrderItem.quantity).label("sold"),
            func.sum(OrderItem.subtotal).label("revenue"),
        )
        .join(OrderItem)
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
        .all()
    )

    # ── Peak hours ──
    hour_data = (
        db.session.query(
            extract("hour", Order.placed_at).label("hour"),
            func.count(Order.id).label("count"),
        )
        .group_by("hour")
        .all()
    )

    # ── Revenue per category ──
    category_revenue = (
        db.session.query(Category.name, func.sum(OrderItem.subtotal).label("revenue"))
        .join(Product, Product.category_id == Category.id)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .group_by(Category.id)
        .order_by(func.sum(OrderItem.subtotal).desc())
        .all()
    )

    # ── Loyalty stats ──
    total_pts_issued = (
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points > 0)
        .scalar()
        or 0
    )
    total_pts_redeemed = abs(
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points < 0)
        .scalar()
        or 0
    )

    # ── Repeat customer rate ──
    repeat_customers = (
        db.session.query(Order.user_id)
        .group_by(Order.user_id)
        .having(func.count(Order.id) > 1)
        .count()
    )
    total_customers = User.query.filter_by(role="customer").count()
    repeat_rate = round(
        (repeat_customers / total_customers * 100) if total_customers else 0, 1
    )

    return render_template(
        "admin/analytics.html",
        monthly_data=monthly_data,
        status_counts=status_counts,
        top_products=top_products,
        hour_data=[(int(h.hour), h.count) for h in hour_data if h.hour is not None],
        category_revenue=category_revenue,
        total_pts_issued=int(total_pts_issued),
        total_pts_redeemed=int(total_pts_redeemed),
        repeat_rate=repeat_rate,
    )


# ── CATEGORIES ───────────────────────────────────────────────
@admin_bp.route("/categories")
@admin_required
def categories():
    cats = Category.query.all()
    return render_template("admin/categories.html", cats=cats)


@admin_bp.route("/categories/add", methods=["POST"])
@admin_required
def add_category():
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "🎂")
    if name and not Category.query.filter_by(name=name).first():
        db.session.add(Category(name=name, icon=icon))
        db.session.commit()
        flash("Category added!", "success")
    return redirect(url_for("admin.categories"))


# ── LOYALTY ADMIN ────────────────────────────────────────────
@admin_bp.route("/loyalty")
@admin_required
def loyalty():
    """Loyalty points leaderboard + adjustment panel."""
    top_users = (
        db.session.query(User, func.sum(LoyaltyLedger.points).label("total_pts"))
        .join(LoyaltyLedger, LoyaltyLedger.user_id == User.id)
        .filter(User.role == "customer")
        .group_by(User.id)
        .order_by(func.sum(LoyaltyLedger.points).desc())
        .limit(50)
        .all()
    )

    total_issued = (
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points > 0)
        .scalar()
        or 0
    )
    total_redeemed = abs(
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points < 0)
        .scalar()
        or 0
    )
    return render_template(
        "admin/loyalty.html",
        top_users=top_users,
        total_issued=int(total_issued),
        total_redeemed=int(total_redeemed),
        loyalty_config=get_loyalty_config(),
    )


@admin_bp.route("/loyalty/adjust", methods=["POST"])
@admin_required
def loyalty_adjust():
    user_id = request.form.get("user_id", type=int)
    points = request.form.get("points", type=int)
    reason = request.form.get("reason", "admin_adj").strip() or "admin_adj"
    if not user_id or points is None:
        flash("User and points are required.", "danger")
        return redirect(url_for("admin.loyalty"))
    user = User.query.get_or_404(user_id)
    LoyaltyLedger.admin_adjust(user_id, points, reason)
    notify(
        user_id,
        "Loyalty Points Updated",
        f"Your points have been adjusted by {points:+d} by the bakery.",
        "loyalty",
    )
    db.session.commit()
    flash(f"Adjusted {points:+d} pts for {user.name}.", "success")
    return redirect(url_for("admin.loyalty"))


# ── INVENTORY ALERT TRIGGER (manual) ─────────────────────────
@admin_bp.route("/inventory/send-alerts", methods=["POST"])
@admin_required
def send_inventory_alerts():
    try:
        check_and_send_inventory_alerts()
        flash("Inventory alert emails sent to admins.", "success")
    except Exception as e:
        flash(f"Alert failed: {e}", "danger")
    return redirect(url_for("admin.inventory"))
