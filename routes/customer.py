from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort, session
from flask_login import login_required, current_user
from app import csrf
from models import (db, Product, ProductVariant, Category, Cart, Wishlist,
                    Order, OrderItem, Payment, Refund, Coupon, Subscription,
                    Review, Message, Notification, AddressChange, ModificationRequest,
                    PaymentLink, LoyaltyLedger, calculate_loyalty_redemption, get_loyalty_config, cache)
from recommendation_engine import get_recommendation_engine
from services import (
    enrich_products,
    get_customer_orders_page,
    get_customer_products_page,
    get_customer_wishlist_page,
    page_args,
)
from utils import (
    extract_address_payload,
    get_saved_addresses_for_user,
    get_selected_saved_address,
    save_address_for_customer,
    validate_address_payload,
)
from datetime import datetime, timedelta
from decimal import Decimal
import random, json, re

customer_bp = Blueprint('customer', __name__)


@customer_bp.before_request
def redirect_delivery_users_to_delivery_portal():
    if current_app.config.get('PORTAL_ROLE') != 'customer':
        from routes.auth import portal_url_for_role
        if request.endpoint == 'customer.home':
            return redirect(url_for('auth.login'))
        if current_user.is_authenticated and current_user.role == 'admin':
            return redirect(portal_url_for_role('admin', url_for('admin.dashboard')))
        if current_user.is_authenticated and current_user.role == 'delivery':
            return redirect(portal_url_for_role('delivery', url_for('delivery.dashboard')))
        abort(404)

    if current_user.is_authenticated and current_user.role == 'delivery':
        from routes.auth import portal_url_for_role
        return redirect(portal_url_for_role('delivery', url_for('delivery.dashboard')))
    if current_user.is_authenticated and current_user.role == 'admin':
        from routes.auth import portal_url_for_role
        return redirect(portal_url_for_role('admin', url_for('admin.dashboard')))


def notify(user_id, title, message, ntype='order', link=''):
    db.session.add(Notification(user_id=user_id, title=title, message=message,
                                type=ntype, link=link))


def wants_json_response():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
        request.accept_mimetypes.best == 'application/json'


def split_preparation_steps(text):
    if not text:
        return []

    steps = []
    for block in re.split(r'[\r\n]+', text):
        block = block.strip(' \t-•')
        if not block:
            continue
        for step in re.split(r'(?<=[.!?])\s+', block):
            step = step.strip(' \t-•')
            if step:
                steps.append(step)
    return steps


def has_delivered_product_order(user_id, product_id):
    return db.session.query(Order.id).join(
        OrderItem, OrderItem.order_id == Order.id
    ).filter(
        Order.user_id == user_id,
        Order.status == 'DELIVERED',
        OrderItem.product_id == product_id,
    ).first() is not None


def resolve_product_variant(product, variant_id=None):
    if variant_id:
        return ProductVariant.query.filter_by(
            id=variant_id,
            product_id=product.id,
        ).first()
    return product.variants.order_by(ProductVariant.id.asc()).first()


def serialize_cart_line(product, variant, quantity, cart_id=None, is_guest=False):
    price = variant.price if variant else product.base_price
    max_qty = variant.stock if variant and variant.stock and variant.stock > 0 else max(int(quantity or 1), 1)
    remove_url = url_for('customer.remove_from_cart', cart_id=cart_id or 0)
    if is_guest:
        remove_url = url_for(
            'customer.remove_from_cart',
            cart_id=0,
            product_id=product.id,
            variant_id=variant.id if variant else None,
        )

    return {
        'cart_id': cart_id,
        'product_id': product.id,
        'variant_id': variant.id if variant else None,
        'product': product,
        'variant': variant,
        'quantity': int(quantity or 1),
        'price': price,
        'line_total': price * int(quantity or 1),
        'max_qty': int(max_qty or 1),
        'image': product.image_src,
        'is_guest': is_guest,
        'remove_url': remove_url,
    }


def set_guest_cart(entries):
    if entries:
        session['guest_cart'] = entries
    else:
        session.pop('guest_cart', None)
    session.modified = True


def load_guest_cart_lines():
    raw_entries = session.get('guest_cart', [])
    normalized_entries = []
    lines = []
    changed = False

    for entry in raw_entries:
        try:
            product_id = int(entry.get('product_id') or 0)
            variant_id = int(entry.get('variant_id') or 0)
            quantity = max(1, int(entry.get('quantity') or 1))
        except (AttributeError, TypeError, ValueError):
            changed = True
            continue

        product = Product.query.get(product_id)
        if not product or not product.is_active:
            changed = True
            continue

        variant = resolve_product_variant(product, variant_id)
        if not variant:
            changed = True
            continue

        normalized_entry = {
            'product_id': product.id,
            'variant_id': variant.id,
            'quantity': quantity,
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
        lines.append(serialize_cart_line(
            product=item.product,
            variant=variant,
            quantity=item.quantity,
            cart_id=item.id,
            is_guest=False,
        ))
    return lines


def calculate_cart_totals(lines):
    subtotal = sum((Decimal(str(line['price'])) * int(line['quantity']) for line in lines), Decimal('0'))
    total_quantity = sum(int(line['quantity']) for line in lines)
    return subtotal, total_quantity


def upsert_guest_cart_item(product, variant, quantity):
    guest_cart = list(session.get('guest_cart', []))
    updated_quantity = quantity

    for entry in guest_cart:
        same_product = int(entry.get('product_id') or 0) == product.id
        same_variant = int(entry.get('variant_id') or 0) == variant.id
        if not (same_product and same_variant):
            continue

        updated_quantity = min(
            max(1, int(entry.get('quantity') or 1) + quantity),
            max(int(variant.stock or 0), 1),
        )
        entry['quantity'] = updated_quantity
        set_guest_cart(guest_cart)
        return serialize_cart_line(product, variant, updated_quantity, is_guest=True)

    updated_quantity = min(max(1, quantity), max(int(variant.stock or 0), 1))
    guest_cart.append({
        'product_id': product.id,
        'variant_id': variant.id,
        'quantity': updated_quantity,
    })
    set_guest_cart(guest_cart)
    return serialize_cart_line(product, variant, updated_quantity, is_guest=True)


def update_guest_cart_item(product_id, variant_id, quantity):
    guest_cart = []
    found = False

    for entry in session.get('guest_cart', []):
        same_product = int(entry.get('product_id') or 0) == product_id
        same_variant = int(entry.get('variant_id') or 0) == variant_id
        if not (same_product and same_variant):
            guest_cart.append(entry)
            continue

        found = True
        if quantity >= 1:
            product = Product.query.get(product_id)
            variant = resolve_product_variant(product, variant_id) if product else None
            available_stock = int(variant.stock or 0) if variant else quantity
            entry['quantity'] = min(quantity, max(available_stock, 1))
            guest_cart.append(entry)

    set_guest_cart(guest_cart)
    return found


def merge_guest_cart_into_user(user_id):
    guest_lines = load_guest_cart_lines()
    if not guest_lines:
        return 0

    merged_items = 0
    for line in guest_lines:
        variant = line['variant']
        available_stock = int(variant.stock or 0) if variant else 0
        if available_stock <= 0:
            continue

        quantity = min(int(line['quantity']), available_stock)
        existing = Cart.query.filter_by(
            user_id=user_id,
            product_id=line['product_id'],
            variant_id=line['variant_id'],
        ).first()
        if existing:
            existing.quantity = min(existing.quantity + quantity, available_stock)
        else:
            db.session.add(Cart(
                user_id=user_id,
                product_id=line['product_id'],
                variant_id=line['variant_id'],
                quantity=quantity,
            ))
        merged_items += quantity

    set_guest_cart([])
    return merged_items


def build_cart_summary(user_id=None, added_item=None):
    lines = get_cart_lines(user_id=user_id)
    subtotal, total_quantity = calculate_cart_totals(lines)
    checkout_url = url_for('customer.checkout')
    if user_id is None and not current_user.is_authenticated:
        checkout_url = url_for('auth.login', next=url_for('customer.checkout'))

    payload = {
        'count': total_quantity,
        'line_count': len(lines),
        'subtotal': float(subtotal),
        'cart_url': url_for('customer.cart'),
        'checkout_url': checkout_url,
        'items': [{
            'name': line['product'].name,
            'variant': line['variant'].name if line['variant'] else '',
            'quantity': line['quantity'],
            'line_total': float(line['line_total']),
            'image': line['image'],
        } for line in lines[:3]],
    }

    if added_item:
        payload['added_item'] = {
            'name': added_item['product'].name,
            'variant': added_item['variant'].name if added_item['variant'] else '',
            'quantity': added_item['quantity'],
            'line_total': float(added_item['line_total']),
            'image': added_item['image'],
        }

    return payload


def create_order_payment_link(order):
    return PaymentLink.create_pending(
        user_id=order.user_id,
        order_id=order.id,
        purpose='ORDER',
        title=f'Payment for Order #{order.order_number}',
        amount=order.total,
        payment_method=order.payment_method,
        success_url=url_for('customer.order_detail', order_id=order.id),
        cancel_url=url_for('customer.order_detail', order_id=order.id),
        notes='Gateway integration pending. Do not mark this payment as completed until the payment provider is connected.',
    )


def create_subscription_payment_link(plan, price, discount_pct, days):
    return PaymentLink.create_pending(
        user_id=current_user.id,
        purpose='SUBSCRIPTION',
        title=f'{plan.title()} Sweet Club Membership',
        amount=Decimal(str(price)),
        payment_method='CARD',
        subscription_plan=plan,
        subscription_discount_pct=Decimal(str(discount_pct)),
        subscription_duration_days=days,
        success_url=url_for('customer.subscription'),
        cancel_url=url_for('customer.subscription'),
        notes='Membership stays inactive until the payment gateway confirms a successful payment.',
    )


# ────────────────────────────────────────
# HOME
# ────────────────────────────────────────
@customer_bp.route('/')
@cache.cached(timeout=300)
def home():
    featured = Product.query.filter_by(is_featured=True, is_active=True).limit(8).all()
    enrich_products(featured)
    categories = Category.query.all()
    occasions  = ['Birthday', 'Wedding', 'Anniversary', 'Baby Shower', 'Corporate']
    return render_template('customer/home.html',
                           featured=featured,
                           categories=categories,
                           occasions=occasions)


# ────────────────────────────────────────
# PRODUCTS
# ────────────────────────────────────────
@customer_bp.route('/products')
@cache.cached(timeout=60, query_string=True)
def products():
    q          = request.args.get('q', '')
    cat_id     = request.args.get('category', type=int)
    eggless    = request.args.get('eggless', type=int)
    min_price  = request.args.get('min_price', type=float)
    max_price  = request.args.get('max_price', type=float)
    occasion   = request.args.get('occasion', '')
    sort = request.args.get('sort', 'featured')
    page, per_page = page_args(default_per_page=12, max_per_page=24)

    pagination = get_customer_products_page({
        'q': q,
        'category': cat_id,
        'eggless': eggless,
        'min_price': min_price,
        'max_price': max_price,
        'occasion': occasion,
        'sort': sort,
    }, page, per_page)
    categories = Category.query.all()
    return render_template('customer/products.html',
                           products=pagination.items, pagination=pagination, categories=categories,
                           q=q, cat_id=cat_id, eggless=eggless,
                           min_price=min_price, max_price=max_price,
                           occasion=occasion, sort=sort)


@customer_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product  = Product.query.get_or_404(product_id)
    enrich_products([product])
    variants = product.variants.all()
    reviews  = product.reviews.order_by(Review.created_at.desc()).all()
    in_wish  = False
    can_review_product = False
    current_review = None
    if current_user.is_authenticated:
        in_wish = Wishlist.query.filter_by(
            user_id=current_user.id, product_id=product_id
        ).first() is not None
        if current_user.role == 'customer':
            current_review = Review.query.filter_by(
                product_id=product_id,
                user_id=current_user.id,
            ).first()
            can_review_product = has_delivered_product_order(current_user.id, product_id)

    # ML Recommendations & Related
    related = []
    from models import cache
    rec_ids = cache.get(f'recommendations_{product_id}')
    if rec_ids:
        # Maintain ML ordering
        unsorted_related = Product.query.filter(Product.id.in_(rec_ids), Product.is_active==True).all()
        related = sorted(unsorted_related, key=lambda x: rec_ids.index(x.id))
        
    if len(related) < 4:
        from sqlalchemy import func
        fallback = Product.query.filter(
            Product.category_id == product.category_id,
            Product.id != product.id,
            Product.id.notin_([r.id for r in related] + [0]),
            Product.is_active == True
        ).order_by(func.random()).limit(4 - len(related)).all()
        related.extend(fallback)

    enrich_products(related)

    return render_template('customer/product_detail.html',
                           product=product, variants=variants,
                           reviews=reviews, in_wish=in_wish, related=related,
                           preparation_steps=split_preparation_steps(product.preparation),
                           can_review_product=can_review_product,
                           current_review=current_review)


# ────────────────────────────────────────
# CART
# ────────────────────────────────────────
@customer_bp.route('/cart')
def cart():
    items = get_cart_lines(current_user.id if current_user.is_authenticated else None)
    subtotal, total_quantity = calculate_cart_totals(items)
    delivery_threshold = Decimal(str(current_app.config.get('DELIVERY_FREE_THRESHOLD', 500)))
    delivery_fee = Decimal(str(current_app.config.get('DELIVERY_CHARGE', 50)))
    delivery_charge = Decimal('0') if subtotal >= delivery_threshold else (delivery_fee if items else Decimal('0'))
    return render_template(
        'customer/cart.html',
        items=items,
        subtotal=subtotal,
        total_quantity=total_quantity,
        delivery_charge=delivery_charge,
        delivery_threshold=delivery_threshold,
        amount_to_free_delivery=max(Decimal('0'), delivery_threshold - subtotal),
    )


@customer_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    product_id = request.form.get('product_id', type=int)
    variant_id = request.form.get('variant_id', type=int)
    quantity   = max(request.form.get('quantity', 1, type=int) or 1, 1)

    product = Product.query.get_or_404(product_id)
    variant = resolve_product_variant(product, variant_id)

    if not variant or variant.stock < quantity:
        if wants_json_response():
            return jsonify({'ok': False, 'message': 'Insufficient stock.'}), 400
        flash('Insufficient stock!', 'danger')
        return redirect(request.referrer or url_for('customer.products'))

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
                quantity=quantity
            )
            db.session.add(cart_item)
        db.session.commit()
        added_item = serialize_cart_line(product, variant, cart_item.quantity, cart_id=cart_item.id)
        summary_user_id = current_user.id
    else:
        added_item = upsert_guest_cart_item(product, variant, quantity)
        summary_user_id = None

    if wants_json_response():
        payload = build_cart_summary(summary_user_id, added_item=added_item)
        payload['ok'] = True
        payload['message'] = f'{product.name} added to cart.'
        return jsonify(payload)

    if current_user.is_authenticated:
        flash(f'{product.name} added to cart! 🛒', 'success')
    else:
        flash(f'{product.name} added to cart. Sign in when you are ready to checkout.', 'success')
    return redirect(request.referrer or url_for('customer.cart'))


@customer_bp.route('/cart/update', methods=['POST'])
def update_cart():
    quantity = max(request.form.get('quantity', type=int) or 1, 1)
    updated_line = None

    if current_user.is_authenticated:
        cart_id = request.form.get('cart_id', type=int)
        item = Cart.query.filter_by(id=cart_id, user_id=current_user.id).first_or_404()
        if quantity < 1:
            db.session.delete(item)
        else:
            item.quantity = min(quantity, item.variant.stock if item.variant else quantity)
        db.session.commit()
        if quantity >= 1:
            variant = item.variant or resolve_product_variant(item.product, item.variant_id)
            updated_line = serialize_cart_line(
                product=item.product,
                variant=variant,
                quantity=item.quantity,
                cart_id=item.id,
                is_guest=False,
            )
        summary_user_id = current_user.id
    else:
        product_id = request.form.get('product_id', type=int)
        variant_id = request.form.get('variant_id', type=int) or 0
        update_guest_cart_item(product_id, variant_id, quantity)
        summary_user_id = None
        updated_line = next((
            line for line in get_cart_lines(None)
            if line['product_id'] == product_id and (line['variant_id'] or 0) == variant_id
        ), None)

    if wants_json_response():
        lines = get_cart_lines(summary_user_id)
        subtotal, total_quantity = calculate_cart_totals(lines)
        delivery_threshold = Decimal(str(current_app.config.get('DELIVERY_FREE_THRESHOLD', 500)))
        delivery_fee = Decimal(str(current_app.config.get('DELIVERY_CHARGE', 50)))
        delivery_charge = Decimal('0') if subtotal >= delivery_threshold else (delivery_fee if lines else Decimal('0'))
        payload = {
            'ok': True,
            'count': total_quantity,
            'line_count': len(lines),
            'subtotal': float(subtotal),
            'delivery_charge': float(delivery_charge),
            'grand_total': float(subtotal + delivery_charge),
            'empty': len(lines) == 0,
            'delivery_threshold': float(delivery_threshold),
        }
        if updated_line:
            payload['item'] = {
                'quantity': updated_line['quantity'],
                'line_total': float(updated_line['line_total']),
                'max_qty': int(updated_line['max_qty']),
            }
        return jsonify(payload)

    return redirect(url_for('customer.cart'))


@customer_bp.route('/cart/remove/<int:cart_id>')
def remove_from_cart(cart_id):
    if current_user.is_authenticated:
        item = Cart.query.filter_by(id=cart_id, user_id=current_user.id).first_or_404()
        db.session.delete(item)
        db.session.commit()
    else:
        product_id = request.args.get('product_id', type=int)
        variant_id = request.args.get('variant_id', type=int) or 0
        update_guest_cart_item(product_id, variant_id, 0)
    flash('Item removed from cart.', 'info')
    return redirect(url_for('customer.cart'))


# ────────────────────────────────────────
# WISHLIST
# ────────────────────────────────────────
@customer_bp.route('/wishlist')
@login_required
def wishlist():
    page, per_page = page_args(default_per_page=12, max_per_page=24)
    pagination = get_customer_wishlist_page(current_user.id, page, per_page)
    return render_template('customer/wishlist.html', items=pagination.items, pagination=pagination)


@customer_bp.route('/wishlist/toggle/<int:product_id>')
@login_required
def toggle_wishlist(product_id):
    Product.query.get_or_404(product_id)
    item = Wishlist.query.filter_by(
        user_id=current_user.id, product_id=product_id
    ).first()
    if item:
        db.session.delete(item)
        flash('Removed from wishlist.', 'info')
    else:
        db.session.add(Wishlist(user_id=current_user.id, product_id=product_id))
        flash('Added to wishlist! ❤️', 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('customer.wishlist'))


# ────────────────────────────────────────
# CHECKOUT & ORDERS
# ────────────────────────────────────────
@customer_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_items = Cart.query.filter_by(user_id=current_user.id).all()
    if not cart_items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('customer.cart'))

    subtotal = sum(
        (i.variant.price if i.variant else i.product.base_price) * i.quantity
        for i in cart_items
    )

    # Apply membership discount
    discount = Decimal('0')
    sub = Subscription.query.filter_by(user_id=current_user.id, is_active=True).first()
    if sub and sub.end_date > datetime.utcnow():
        discount = (subtotal * sub.discount_pct / 100).quantize(Decimal('0.01'))

    delivery_threshold = Decimal(str(current_app.config.get('DELIVERY_FREE_THRESHOLD', 500)))
    delivery_fee = Decimal(str(current_app.config.get('DELIVERY_CHARGE', 50)))
    delivery_charge = delivery_fee if subtotal < delivery_threshold else Decimal('0')
    loyalty_balance = current_user.loyalty_points
    loyalty_preview = calculate_loyalty_redemption(0, subtotal, loyalty_balance)
    loyalty_rules = get_loyalty_config()
    total = subtotal - discount + delivery_charge

    time_slots = current_app.config['TIME_SLOTS']
    saved_addresses = get_saved_addresses_for_user(current_user.id)
    default_saved_address = next((addr for addr in saved_addresses if addr.is_default), saved_addresses[0] if saved_addresses else None)
    selected_address_id = default_saved_address.id if default_saved_address else None
    checkout_address = extract_address_payload({}, fallback_address=default_saved_address, default_phone=current_user.phone or '') if default_saved_address else {
        'label': 'Saved Address',
        'address_line1': '',
        'address_line2': '',
        'city': '',
        'pincode': '',
        'phone': current_user.phone or '',
    }

    if request.method == 'POST':
        coupon_code = request.form.get('coupon_code', '').strip().upper()
        coupon_discount = Decimal('0')
        loyalty_points_requested = request.form.get('loyalty_points', type=int) or 0
        loyalty_points_applied = 0
        loyalty_discount = Decimal('0')
        delivery_date_raw = request.form.get('delivery_date', '').strip()
        selected_address_id = request.form.get('selected_address_id', type=int)
        selected_saved_address = get_selected_saved_address(current_user.id, selected_address_id)
        checkout_address = extract_address_payload(
            request.form,
            fallback_address=selected_saved_address,
            default_phone=current_user.phone or '',
        )

        try:
            delivery_date = datetime.strptime(delivery_date_raw, '%Y-%m-%d').date()
        except ValueError:
            flash('Please select a valid delivery date.', 'danger')
            return redirect(url_for('customer.checkout'))

        earliest_delivery_date = datetime.utcnow().date() + timedelta(days=1)
        if delivery_date < earliest_delivery_date:
            flash('Please choose a delivery date from tomorrow onward.', 'danger')
            return redirect(url_for('customer.checkout'))

        selected_time_slot = request.form.get('time_slot', '').strip()
        if selected_time_slot not in time_slots:
            flash('Please choose a valid delivery time slot.', 'danger')
            return redirect(url_for('customer.checkout'))

        address_errors = validate_address_payload(checkout_address)
        if address_errors:
            flash(address_errors[0], 'danger')
            return redirect(url_for('customer.checkout'))

        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            if coupon and coupon.is_valid() and subtotal >= coupon.min_order_value:
                if coupon.discount_type == 'percentage':
                    coupon_discount = (subtotal * coupon.discount_value / 100).quantize(Decimal('0.01'))
                else:
                    coupon_discount = coupon.discount_value
                coupon.used_count += 1
            elif coupon_code:
                flash('Invalid or expired coupon code.', 'warning')

        loyalty_result = calculate_loyalty_redemption(loyalty_points_requested, subtotal, loyalty_balance)
        loyalty_points_applied = loyalty_result['points_applied']
        loyalty_discount = Decimal(str(loyalty_result['discount']))
        if loyalty_points_requested and loyalty_points_applied <= 0:
            flash('Those loyalty points cannot be applied to this order.', 'warning')
            return redirect(url_for('customer.checkout'))

        total_discount = discount + coupon_discount + loyalty_discount
        final_total = subtotal - total_discount + delivery_charge

        # Lock rows to prevent race conditions during checkout
        for item in cart_items:
            v = ProductVariant.query.with_for_update().get(item.variant_id) if item.variant else None
            if item.variant and (not v or v.stock < item.quantity):
                flash(f'Sorry, {item.product.name} is out of stock.', 'danger')
                db.session.rollback()
                return redirect(url_for('customer.cart'))
            for recipe_item in item.product.recipe_items.all():
                from models import RawMaterial
                material = RawMaterial.query.with_for_update().get(recipe_item.raw_material_id)
                required_qty = Decimal(recipe_item.quantity_required) * item.quantity
                if material and material.is_active and Decimal(material.stock) < required_qty:
                    flash(
                        f'Not enough {material.name} is available to complete {item.product.name} right now.',
                        'danger'
                    )
                    db.session.rollback()
                    return redirect(url_for('customer.cart'))

        # Create order
        order = Order(user_id=current_user.id)
        order.order_number    = order.generate_order_number()
        order.subtotal        = subtotal
        order.discount        = discount + coupon_discount
        order.loyalty_discount = loyalty_discount
        order.delivery_charge = delivery_charge
        order.total           = final_total
        order.address_line1   = checkout_address['address_line1']
        order.address_line2   = checkout_address['address_line2']
        order.city            = checkout_address['city']
        order.pincode         = checkout_address['pincode']
        order.phone           = checkout_address['phone'] or current_user.phone
        order.delivery_slot   = selected_time_slot
        order.delivery_date   = delivery_date
        order.special_note    = request.form.get('special_note')
        order.occasion        = request.form.get('occasion')
        order.payment_method  = request.form.get('payment_method', 'COD')
        order.payment_status  = 'PENDING'
        order.coupon_code     = coupon_code if coupon_discount > 0 else None
        order.status          = 'PLACED'
        db.session.add(order)
        db.session.flush()

        if loyalty_points_applied > 0:
            LoyaltyLedger.redeem(current_user.id, order.id, loyalty_points_applied)

        for item in cart_items:
            price = item.variant.price if item.variant else item.product.base_price
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                product_name=item.product.name,
                variant_name=item.variant.name if item.variant else '',
                quantity=item.quantity,
                unit_price=price,
                subtotal=price * item.quantity
            ))
            # Deduct stock
            if item.variant:
                v = ProductVariant.query.with_for_update().get(item.variant_id)
                v.stock -= item.quantity
            for recipe_item in item.product.recipe_items.all():
                from models import RawMaterial
                material = RawMaterial.query.with_for_update().get(recipe_item.raw_material_id)
                if material and material.is_active:
                    material.stock = max(
                        Decimal('0'),
                        Decimal(material.stock) - (Decimal(recipe_item.quantity_required) * item.quantity)
                    )

        # Payment record
        db.session.add(Payment(
            order_id=order.id, amount=final_total,
            status='PENDING',
            method=order.payment_method,
            transaction_id=f'TXN{random.randint(100000,999999)}'
        ))

        payment_link = None
        if order.payment_method in ['UPI', 'CARD']:
            payment_link = create_order_payment_link(order)

        if request.form.get('save_address_for_future'):
            save_address_for_customer(
                user_id=current_user.id,
                payload=checkout_address,
                make_default=bool(request.form.get('make_default')),
            )

        # Clear cart
        Cart.query.filter_by(user_id=current_user.id).delete()

        # Notify
        notify(current_user.id, 'Order Placed! 🎉',
               f'Your order #{order.order_number} has been placed successfully.',
               'order', url_for('customer.order_detail', order_id=order.id))

        db.session.commit()
        if payment_link:
            flash('Order created. Complete payment after the gateway is integrated using the payment page below.', 'info')
            return redirect(url_for('customer.payment_link_page', token=payment_link.token))

        flash(f'Order #{order.order_number} placed successfully!', 'success')
        return redirect(url_for('customer.order_detail', order_id=order.id))

    return render_template('customer/checkout.html',
                           cart_items=cart_items, subtotal=subtotal,
                           discount=discount, delivery_charge=delivery_charge,
                           total=total, time_slots=time_slots,
                           has_subscription=bool(sub),
                           saved_addresses=saved_addresses,
                           selected_address_id=selected_address_id,
                           checkout_address=checkout_address,
                           loyalty_balance=loyalty_balance,
                           loyalty_preview=loyalty_preview,
                           loyalty_rules=loyalty_rules,
                           delivery_threshold=delivery_threshold,
                           delivery_fee=delivery_fee,
                           earliest_delivery_date=(datetime.utcnow().date() + timedelta(days=1)).isoformat())


@customer_bp.route('/orders')
@login_required
def order_history():
    page, per_page = page_args(default_per_page=8, max_per_page=16)
    pagination = get_customer_orders_page(current_user.id, page, per_page)
    return render_template('customer/orders.html', orders=pagination.items, pagination=pagination)


@customer_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    items = order.items.all()
    can_cancel = order.can_cancel()
    can_modify = order.can_modify()
    can_change_addr = order.can_change_address()
    pending_payment_link = PaymentLink.query.filter_by(
        user_id=current_user.id,
        order_id=order.id,
        purpose='ORDER',
        status='PENDING',
    ).order_by(PaymentLink.id.desc()).first()
    return render_template('customer/order_detail.html',
                           order=order, items=items,
                           can_cancel=can_cancel,
                           can_modify=can_modify,
                           can_change_addr=can_change_addr,
                           pending_payment_link=pending_payment_link)


@customer_bp.route('/payments/<token>')
@login_required
def payment_link_page(token):
    payment_link = PaymentLink.query.filter_by(token=token).first_or_404()
    if current_user.role != 'admin' and payment_link.user_id != current_user.id:
        abort(403)

    return render_template(
        'customer/payment_link.html',
        payment_link=payment_link,
        related_order=payment_link.order,
    )


@customer_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_cancel():
        flash('Order cannot be cancelled at this stage (must be within 2 minutes of placing).', 'danger')
        return redirect(url_for('customer.order_detail', order_id=order_id))

    # Restore stock
    for item in order.items.all():
        if item.variant_id:
            v = ProductVariant.query.get(item.variant_id)
            if v:
                v.stock += item.quantity

    order.status = 'CANCELLED'

    # Refund if paid
    if order.payment and order.payment.status == 'PAID':
        db.session.add(Refund(order_id=order.id, amount=order.total,
                              reason='Customer cancelled order', status='PROCESSING'))

    notify(current_user.id, 'Order Cancelled',
           f'Order #{order.order_number} has been cancelled.',
           'order', url_for('customer.order_detail', order_id=order.id))
    db.session.commit()
    flash('Order cancelled successfully.', 'success')
    return redirect(url_for('customer.order_history'))


@customer_bp.route('/orders/<int:order_id>/reorder')
@login_required
def reorder(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    added = 0
    skipped = []
    for item in order.items.all():
        variant = ProductVariant.query.get(item.variant_id) if item.variant_id else None
        if variant and variant.stock > 0:
            quantity_to_add = min(item.quantity, variant.stock)
            existing = Cart.query.filter_by(
                user_id=current_user.id, product_id=item.product_id, variant_id=item.variant_id
            ).first()
            if existing:
                existing.quantity = min(existing.quantity + quantity_to_add, variant.stock)
            else:
                db.session.add(Cart(user_id=current_user.id,
                                    product_id=item.product_id,
                                    variant_id=item.variant_id,
                                    quantity=quantity_to_add))
            added += quantity_to_add
        else:
            skipped.append(item.product_name)
    db.session.commit()
    if added:
        flash(f'{added} item(s) added to cart!', 'success')
    if skipped:
        flash('Some previous items are unavailable right now: ' + ', '.join(skipped[:3]), 'warning')
    return redirect(url_for('customer.cart'))


@customer_bp.route('/orders/<int:order_id>/change-address', methods=['POST'])
@login_required
def change_address(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_change_address():
        flash('Address cannot be changed at this stage.', 'danger')
        return redirect(url_for('customer.order_detail', order_id=order_id))

    old_addr = f"{order.address_line1}, {order.address_line2}, {order.city} - {order.pincode}"
    order.address_line1 = request.form.get('address_line1', order.address_line1)
    order.address_line2 = request.form.get('address_line2', order.address_line2)
    order.city          = request.form.get('city', order.city)
    order.pincode       = request.form.get('pincode', order.pincode)
    order.address_changes += 1

    new_addr = f"{order.address_line1}, {order.address_line2}, {order.city} - {order.pincode}"
    db.session.add(AddressChange(order_id=order.id, old_address=old_addr,
                                  new_address=new_addr, changed_by=current_user.id))
    db.session.commit()
    flash('Delivery address updated!', 'success')
    return redirect(url_for('customer.order_detail', order_id=order_id))


@customer_bp.route('/orders/<int:order_id>/modify', methods=['POST'])
@login_required
def request_modification(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    if not order.can_modify():
        flash('Order cannot be modified at this stage.', 'danger')
        return redirect(url_for('customer.order_detail', order_id=order_id))

    description = request.form.get('description', '')
    order.is_locked = True
    db.session.add(ModificationRequest(
        order_id=order.id, user_id=current_user.id, description=description
    ))
    db.session.commit()
    flash('Modification request submitted. Admin will review shortly.', 'success')
    return redirect(url_for('customer.order_detail', order_id=order_id))


# ────────────────────────────────────────
# REVIEWS
# ────────────────────────────────────────
@customer_bp.route('/review/add', methods=['POST'])
@login_required
def add_review():
    product_id = request.form.get('product_id', type=int)
    rating     = request.form.get('rating', type=int)
    comment    = request.form.get('comment', '')

    if current_user.role != 'customer':
        flash('Only customers can submit reviews.', 'danger')
        return redirect(url_for('customer.product_detail', product_id=product_id))

    if not rating or rating < 1 or rating > 5:
        flash('Please choose a rating between 1 and 5.', 'danger')
        return redirect(url_for('customer.product_detail', product_id=product_id))

    if not has_delivered_product_order(current_user.id, product_id):
        flash('Reviews can be added only after this product has been delivered to you.', 'warning')
        return redirect(url_for('customer.product_detail', product_id=product_id))

    existing = Review.query.filter_by(
        product_id=product_id, user_id=current_user.id
    ).first()
    if existing:
        existing.rating  = rating
        existing.comment = comment
    else:
        db.session.add(Review(product_id=product_id, user_id=current_user.id,
                              rating=rating, comment=comment))
    db.session.commit()
    flash('Review submitted! Thank you.', 'success')
    return redirect(url_for('customer.product_detail', product_id=product_id))


# ────────────────────────────────────────
# MESSAGES / CHAT
# ────────────────────────────────────────
@customer_bp.route('/chat')
@login_required
def chat():
    from models import User
    admin = User.query.filter_by(role='admin').first()
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == admin.id)) |
        ((Message.sender_id == admin.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.sent_at.asc()).all()

    # Mark as read
    Message.query.filter_by(receiver_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return render_template('customer/chat.html', messages=messages, admin=admin)


@customer_bp.route('/chat/send', methods=['POST'])
@login_required
def send_message():
    from models import User
    content = request.form.get('content', '').strip()
    admin = User.query.filter_by(role='admin').first()
    if content and admin:
        db.session.add(Message(sender_id=current_user.id,
                               receiver_id=admin.id, content=content))
        db.session.commit()
    return redirect(url_for('customer.chat'))


@customer_bp.route('/chat/ai', methods=['POST'])
@login_required
@csrf.exempt
def ai_recommend():
    payload = request.get_json(silent=True) or {}
    query = (payload.get('query') or '').strip()
    if not query:
        return jsonify({'ok': False, 'message': 'Tell us what kind of bakery item you are looking for.'}), 400

    engine = get_recommendation_engine()
    products, message = engine.recommend(current_user.id, query, limit=6)
    result = {
        'ok': True,
        'message': message,
        'products': [
            {
                'id': product.id,
                'name': product.name,
                'price': float(product.base_price),
                'category': product.category.name if product.category else '',
                'image': product.image_src,
                'description': product.description or '',
            }
            for product in products
        ],
    }
    return jsonify(result)


# ────────────────────────────────────────
# NOTIFICATIONS
# ────────────────────────────────────────
@customer_bp.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
               .order_by(Notification.created_at.desc()).all()
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    return render_template('customer/notifications.html', notifs=notifs)


# ────────────────────────────────────────
# SUBSCRIPTIONS
# ────────────────────────────────────────
@customer_bp.route('/subscription')
@login_required
def subscription():
    sub = Subscription.query.filter_by(user_id=current_user.id, is_active=True).first()
    pending_subscription_payment = PaymentLink.query.filter_by(
        user_id=current_user.id,
        purpose='SUBSCRIPTION',
        status='PENDING',
    ).order_by(PaymentLink.id.desc()).first()
    return render_template(
        'customer/subscription.html',
        sub=sub,
        pending_subscription_payment=pending_subscription_payment,
    )


@customer_bp.route('/subscription/subscribe', methods=['POST'])
@login_required
def subscribe():
    plan = request.form.get('plan', 'monthly')
    prices = {'monthly': (199, 10, 30), 'yearly': (1499, 15, 365)}
    price, disc, days = prices.get(plan, prices['monthly'])
    payment_link = create_subscription_payment_link(plan, price, disc, days)
    db.session.commit()
    flash('Payment page opened. Membership will stay inactive until the payment gateway is connected and confirms success.', 'info')
    return redirect(url_for('customer.payment_link_page', token=payment_link.token))


# ────────────────────────────────────────
# INVOICE
# ────────────────────────────────────────
@customer_bp.route('/orders/<int:order_id>/invoice')
@login_required
def invoice(order_id):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()
    items = order.items.all()
    return render_template('customer/invoice.html', order=order, items=items)
