from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from bootstrap import get_container
from models import Product, ProductVariant, Coupon, Notification, calculate_loyalty_redemption, get_loyalty_config
from decimal import Decimal, InvalidOperation

api_bp = Blueprint('api', __name__)


@api_bp.route('/validate-coupon', methods=['POST'])
@login_required
def validate_coupon():
    data = request.get_json() or {}
    result = get_container().payment_service.validate_coupon(
        data.get('code', ''),
        data.get('subtotal', 0),
    )
    return jsonify(result)


@api_bp.route('/notifications/unread-count')
@login_required
def unread_notif_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})


@api_bp.route('/cart/count')
def cart_count():
    from routes.customer import build_cart_summary
    summary = build_cart_summary(current_user.id if current_user.is_authenticated else None)
    return jsonify({'count': summary['count'], 'line_count': summary['line_count']})


@api_bp.route('/cart/summary')
def cart_summary():
    from routes.customer import build_cart_summary
    return jsonify(build_cart_summary(current_user.id if current_user.is_authenticated else None))


@api_bp.route('/product/<int:product_id>/variants')
def product_variants(product_id):
    variants = ProductVariant.query.filter_by(product_id=product_id).all()
    return jsonify([{
        'id': v.id, 'name': v.name,
        'price': float(v.price), 'stock': v.stock
    } for v in variants])


@api_bp.route('/search/suggestions')
def search_suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    products = get_container().product_repository.active_search(q, limit=5)
    return jsonify([{'id': p.id, 'name': p.name, 'price': float(p.base_price)} for p in products])


# ── LOYALTY API ──────────────────────────────────────────────
@api_bp.route('/loyalty/balance')
@login_required
def loyalty_balance():
    """Return the current user's loyalty points balance."""
    loyalty = get_loyalty_config()
    redeem_per = max(1, loyalty['LOYALTY_REDEEM_PER'])
    redeem_rate = max(1, loyalty['LOYALTY_REDEEM_RATE'])
    pts = current_user.loyalty_points
    max_discount = (pts // redeem_per) * redeem_rate
    return jsonify({
        'points':        pts,
        'tier':          current_user.loyalty_tier,
        'earn_rate':     f'₹{loyalty["LOYALTY_EARN_PER"]} = {loyalty["LOYALTY_EARN_RATE"]} pt',
        'redeem_rate':   f'{redeem_per} pts = ₹{redeem_rate} off',
        'max_discount':  max_discount,
        'can_redeem':    pts >= redeem_per,
    })


@api_bp.route('/loyalty/validate-redeem', methods=['POST'])
@login_required
def loyalty_validate_redeem():
    """Validate a loyalty points redemption request."""
    data = request.get_json() or {}
    loyalty = get_loyalty_config()
    redeem_per = max(1, loyalty['LOYALTY_REDEEM_PER'])
    redeem_rate = max(1, loyalty['LOYALTY_REDEEM_RATE'])

    try:
        points_to_use = int(data.get('points', 0))
    except (TypeError, ValueError):
        return jsonify({'valid': False, 'message': 'Enter a valid whole number of points.'})

    try:
        subtotal = Decimal(str(data.get('subtotal', 0)))
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({'valid': False, 'message': 'Invalid subtotal.'})

    if points_to_use <= 0:
        return jsonify({'valid': False, 'message': 'Enter points to redeem.'})
    if points_to_use > current_user.loyalty_points:
        return jsonify({'valid': False, 'message': 'Not enough loyalty points.'})
    if points_to_use < redeem_per:
        return jsonify({'valid': False,
                        'message': f'Minimum {redeem_per} points required.'})

    loyalty_result = calculate_loyalty_redemption(points_to_use, subtotal, current_user.loyalty_points)
    requested_discount = Decimal(str(loyalty_result['requested_discount']))
    applied_discount = Decimal(str(loyalty_result['discount']))
    capped = loyalty_result['capped']

    if capped:
        message = (
            f'{points_to_use} pts requested ₹{requested_discount:.0f} off, '
            f'but this order can apply {loyalty_result["points_applied"]} pts for ₹{applied_discount:.2f}.'
        )
    else:
        message = f'{loyalty_result["points_applied"]} pts = ₹{applied_discount:.2f} off'

    return jsonify({
        'valid':              True,
        'discount':           float(applied_discount),
        'requested_discount': float(requested_discount),
        'points_applied':     loyalty_result['points_applied'],
        'capped':             capped,
        'message':            message,
    })
