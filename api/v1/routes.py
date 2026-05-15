from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from bootstrap import get_container
from models import Notification, Product, ProductVariant, calculate_loyalty_redemption, get_loyalty_config

api_v1_bp = Blueprint("api_v1", __name__)


@api_v1_bp.route("/meta")
def meta():
    return jsonify({"version": "v1", "status": "ok"})


@api_v1_bp.route("/validate-coupon", methods=["POST"])
@login_required
def validate_coupon():
    data = request.get_json() or {}
    result = get_container().payment_service.validate_coupon(
        data.get("code", ""),
        data.get("subtotal", 0),
    )
    return jsonify(result)


@api_v1_bp.route("/notifications/unread-count")
@login_required
def unread_notif_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({"count": count})


@api_v1_bp.route("/product/<int:product_id>/variants")
def product_variants(product_id):
    variants = ProductVariant.query.filter_by(product_id=product_id).all()
    return jsonify(
        [
            {
                "id": variant.id,
                "name": variant.name,
                "price": float(variant.price),
                "stock": variant.stock,
            }
            for variant in variants
        ]
    )


@api_v1_bp.route("/search/suggestions")
def search_suggestions():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    products = get_container().product_repository.active_search(q, limit=5)
    return jsonify(
        [{"id": product.id, "name": product.name, "price": float(product.base_price)} for product in products]
    )


@api_v1_bp.route("/loyalty/balance")
@login_required
def loyalty_balance():
    loyalty = get_loyalty_config()
    redeem_per = max(1, loyalty["LOYALTY_REDEEM_PER"])
    redeem_rate = max(1, loyalty["LOYALTY_REDEEM_RATE"])
    points = current_user.loyalty_points
    max_discount = (points // redeem_per) * redeem_rate
    return jsonify(
        {
            "points": points,
            "tier": current_user.loyalty_tier,
            "earn_rate": f'₹{loyalty["LOYALTY_EARN_PER"]} = {loyalty["LOYALTY_EARN_RATE"]} pt',
            "redeem_rate": f"{redeem_per} pts = ₹{redeem_rate} off",
            "max_discount": max_discount,
            "can_redeem": points >= redeem_per,
        }
    )


@api_v1_bp.route("/loyalty/validate-redeem", methods=["POST"])
@login_required
def loyalty_validate_redeem():
    data = request.get_json() or {}
    loyalty = get_loyalty_config()
    redeem_per = max(1, loyalty["LOYALTY_REDEEM_PER"])
    redeem_rate = max(1, loyalty["LOYALTY_REDEEM_RATE"])

    try:
        points_to_use = int(data.get("points", 0))
    except (TypeError, ValueError):
        return jsonify({"valid": False, "message": "Enter a valid whole number of points."})

    try:
        subtotal = Decimal(str(data.get("subtotal", 0)))
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({"valid": False, "message": "Invalid subtotal."})

    if points_to_use <= 0:
        return jsonify({"valid": False, "message": "Enter points to redeem."})
    if points_to_use > current_user.loyalty_points:
        return jsonify({"valid": False, "message": "Not enough loyalty points."})
    if points_to_use < redeem_per:
        return jsonify({"valid": False, "message": f"Minimum {redeem_per} points required."})

    loyalty_result = calculate_loyalty_redemption(
        points_to_use,
        subtotal,
        current_user.loyalty_points,
    )
    requested_discount = Decimal(str(loyalty_result["requested_discount"]))
    applied_discount = Decimal(str(loyalty_result["discount"]))

    if loyalty_result["capped"]:
        message = (
            f'{points_to_use} pts requested ₹{requested_discount:.0f} off, '
            f'but this order can apply {loyalty_result["points_applied"]} pts for ₹{applied_discount:.2f}.'
        )
    else:
        message = f'{loyalty_result["points_applied"]} pts = ₹{applied_discount:.2f} off'

    return jsonify(
        {
            "valid": True,
            "discount": float(applied_discount),
            "requested_discount": float(requested_discount),
            "points_applied": loyalty_result["points_applied"],
            "capped": loyalty_result["capped"],
            "message": message,
        }
    )
