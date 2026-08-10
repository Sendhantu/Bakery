from flask import Blueprint, current_app, jsonify, request, session
from flask_login import login_required, current_user
from app import csrf
from bootstrap import get_container
from models import Product, ProductVariant, Coupon, Notification, db, calculate_loyalty_redemption, get_loyalty_config
from decimal import Decimal, InvalidOperation
from utils import reverse_geocode

api_bp = Blueprint('api', __name__)


@api_bp.route('/consent', methods=['POST'])
def update_consent():
    data = request.get_json(silent=True) or {}
    category = data.get('category', 'analytics')
    status = data.get('status', 'declined')
    try:
        get_container().conversion_service.record_consent(
            user_id=current_user.id if current_user.is_authenticated else None,
            category=category,
            status=status,
            source='preference_center',
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'message': str(exc)}), 400
    return jsonify({'ok': True, 'category': category, 'status': status})


@api_bp.route('/analytics/conversion', methods=['POST'])
def record_conversion():
    data = request.get_json(silent=True) or {}
    event_name = data.get('event_name') or data.get('name')
    campaign = data.get('campaign') or {}
    try:
        event = get_container().conversion_service.record_event(
            event_name,
            user_id=current_user.id if current_user.is_authenticated else None,
            event_id=data.get('event_id'),
            product_id=data.get('product_id'),
            order_id=data.get('order_id'),
            table_id=session.get('table_menu', {}).get('table_id') if isinstance(session.get('table_menu'), dict) else None,
            branch_id=data.get('branch_id'),
            amount=data.get('amount'),
            path=data.get('path') or request.path,
            source=campaign.get('source') or data.get('source'),
            medium=campaign.get('medium') or data.get('medium'),
            campaign=campaign.get('campaign') or data.get('campaign_name'),
            content=campaign.get('content') or data.get('content'),
            term=campaign.get('term') or data.get('term'),
            metadata=data.get('metadata') or {},
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'ok': False, 'message': str(exc)}), 400
    return jsonify({'ok': True, 'recorded': bool(event)})


@api_bp.route('/webhooks/<provider>', methods=['POST'])
@csrf.exempt
def signed_webhook(provider):
    payload = request.get_data(cache=False) or b''
    signature = (
        request.headers.get('X-Webhook-Signature')
        or request.headers.get('X-Signature')
        or request.headers.get('X-Hub-Signature-256')
        or ''
    )
    event_id = (
        request.headers.get('X-Webhook-Event-Id')
        or request.headers.get('X-Event-Id')
        or request.headers.get('Idempotency-Key')
        or ''
    )
    event_type = request.headers.get('X-Webhook-Event-Type') or request.headers.get('X-Event-Type')
    timestamp = request.headers.get('X-Webhook-Timestamp') or request.headers.get('X-Timestamp')
    log, valid = get_container().security_service.verify_webhook(
        provider,
        payload,
        signature,
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp,
    )
    db.session.commit()
    if not valid:
        current_app.logger.warning(
            'webhook_rejected provider=%s event_id=%s status=%s',
            provider,
            event_id,
            log.signature_status,
        )
        return jsonify({'ok': False, 'message': 'Webhook verification failed.'}), 401
    return jsonify({'ok': True, 'status': 'verified'})


@api_bp.route('/validate-coupon', methods=['POST'])
@login_required
def validate_coupon():
    data = request.get_json() or {}
    result = get_container().payment_service.validate_coupon(
        data.get('code', ''),
        data.get('subtotal', 0),
        user=current_user,
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


@api_bp.route('/location/reverse-geocode')
@login_required
def reverse_geocode_location():
    latitude = request.args.get('lat')
    longitude = request.args.get('lng')

    try:
        payload = reverse_geocode(latitude, longitude)
    except ValueError as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 400
    except Exception:
        return jsonify({
            'ok': False,
            'message': 'We found the map pin, but could not auto-fill the address right now. Please check the address fields manually.',
        }), 502

    return jsonify(
        {
            'ok': True,
            'location': payload,
            'message': 'Exact location captured and address fields updated.',
        }
    )


@api_bp.route('/delivery/serviceability', methods=['POST'])
@login_required
def delivery_serviceability():
    data = request.get_json() or {}
    result = get_container().delivery_zone_service.check_serviceability(
        branch_id=data.get('branch_id'),
        pincode=data.get('pincode'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        order_subtotal=data.get('subtotal', 0),
    )
    status_code = 200 if result.serviceable else 422
    return jsonify({'ok': result.serviceable, **result.as_dict()}), status_code


@api_bp.route('/search/suggestions')
def search_suggestions():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    products = get_container().product_repository.active_search(q, limit=5)
    return jsonify([{'id': p.id, 'name': p.name, 'price': float(p.current_price)} for p in products])


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
        return jsonify(
            {'valid': False, 'message': 'Enter a valid whole number of points.'}
        )

    try:
        subtotal = Decimal(str(data.get('subtotal', 0)))
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({'valid': False, 'message': 'Invalid subtotal.'})

    if points_to_use <= 0:
        return jsonify({'valid': False, 'message': 'Enter points to redeem.'})
    if points_to_use > current_user.loyalty_points:
        return jsonify({'valid': False, 'message': 'Not enough loyalty points.'})
    if points_to_use < redeem_per:
        return jsonify(
            {'valid': False, 'message': f'Minimum {redeem_per} points required.'}
        )
    if points_to_use % redeem_per != 0:
        return jsonify(
            {
                'valid': False,
                'message': (
                    f'Points can be redeemed only in multiples of {redeem_per}.'
                ),
            }
        )

    loyalty_result = calculate_loyalty_redemption(
        points_to_use, subtotal, current_user.loyalty_points
    )
    requested_discount = Decimal(str(loyalty_result['requested_discount']))
    applied_discount = Decimal(str(loyalty_result['discount']))
    capped = loyalty_result['capped']

    if loyalty_result.get('below_minimum'):
        return jsonify(
            {
                'valid': False,
                'discount': 0,
                'requested_discount': float(requested_discount),
                'points_applied': 0,
                'capped': False,
                'min_points_required': loyalty_result['min_points_required'],
                'min_required_discount': loyalty_result['min_required_discount'],
                'message': (
                    f'Orders above ₹{loyalty_result["min_order_value"]} need at least '
                    f'{loyalty_result["min_points_required"]} points '
                    f'(₹{loyalty_result["min_required_discount"]:.2f}) to redeem.'
                ),
            }
        )

    if capped:
        message = (
            f'{points_to_use} pts requested ₹{requested_discount:.0f} off, '
            f'but this order can apply {loyalty_result["points_applied"]} pts '
            f'for ₹{applied_discount:.2f}.'
        )
    else:
        message = (
            f'{loyalty_result["points_applied"]} pts = ₹{applied_discount:.2f} off'
        )

    return jsonify({
        'valid':              True,
        'discount':           float(applied_discount),
        'requested_discount': float(requested_discount),
        'points_applied':     loyalty_result['points_applied'],
        'capped':             capped,
        'message':            message,
    })
