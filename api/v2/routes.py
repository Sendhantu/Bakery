import time

from flask import Blueprint, g, jsonify, request
from flask_login import current_user

try:
    from flask_jwt_extended import (
        create_access_token,
        create_refresh_token,
        get_jwt_identity,
        jwt_required,
    )
except ImportError:  # pragma: no cover
    create_access_token = None
    create_refresh_token = None
    get_jwt_identity = None

    def jwt_required(*args, **kwargs):  # type: ignore
        def decorator(view):
            return view

        return decorator

from bootstrap import get_container
from models import ApiUsageLog, Order, PushDevice, User, db
from utils import ADMIN_PORTAL_ROLES, has_role

api_v2_bp = Blueprint("api_v2", __name__)


@api_v2_bp.before_request
def record_api_start():
    g.api_started_at = time.perf_counter()


@api_v2_bp.after_request
def record_api_usage(response):
    try:
        duration_ms = int((time.perf_counter() - getattr(g, "api_started_at", time.perf_counter())) * 1000)
        db.session.add(
            ApiUsageLog(
                user_id=current_user.id if getattr(current_user, "is_authenticated", False) else None,
                version="v2",
                path=request.path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=duration_ms,
            )
        )
        db.session.commit()
        response.headers["X-API-Version"] = "v2"
    except Exception:
        db.session.rollback()
    return response


def _jwt_available():
    return create_access_token is not None and create_refresh_token is not None


@api_v2_bp.route("/meta")
def meta():
    return jsonify(
        {
            "version": "v2",
            "status": "active",
            "supported_auth": ["session", "jwt"],
            "public_portal": "customer",
            "private_portals": ["admin", "delivery"],
        }
    )


@api_v2_bp.route("/auth/token", methods=["POST"])
def token():
    if not _jwt_available():
        return jsonify({"ok": False, "message": "JWT support is not installed."}), 501

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password", "")
    user = get_container().auth_service.get_user_by_email(email)
    if user is None or not user.check_password(password) or not user.is_active:
        return jsonify({"ok": False, "message": "Invalid credentials."}), 401

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role, "portal": "delivery" if user.role == "delivery" else "admin"},
    )
    refresh_token = create_refresh_token(identity=str(user.id))
    return jsonify(
        {
            "ok": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "role": user.role,
        }
    )


@api_v2_bp.route("/me")
@jwt_required(optional=True)
def me():
    identity = get_jwt_identity() if get_jwt_identity else None
    if identity:
        user = db.session.get(User, int(identity))
    elif getattr(current_user, "is_authenticated", False):
        user = current_user
    else:
        user = None

    if user is None:
        return jsonify({"authenticated": False}), 401
    return jsonify(
        {
            "authenticated": True,
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "branch_id": user.branch_id,
        }
    )


@api_v2_bp.route("/search/suggestions")
def search_suggestions():
    query_text = (request.args.get("q") or "").strip()
    repository = get_container().product_repository
    if len(query_text) < 2:
        products = repository.trending_products(limit=5)
    else:
        products = repository.active_search(query_text, limit=5)
    return jsonify(
        [
            {
                "id": product.id,
                "name": product.name,
                "price": float(product.current_price),
                "image": product.image_src,
            }
            for product in products
        ]
    )


@api_v2_bp.route("/qr/verify", methods=["GET", "POST"])
def verify_qr_token():
    token = (request.values.get("token") or "").strip()
    try:
        order = get_container().qr_service.verify_token(
            token,
            actor_id=current_user.id if getattr(current_user, "is_authenticated", False) else None,
        )
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "verified_at": order.qr_verified_at.isoformat() if order.qr_verified_at else None,
        }
    )


@api_v2_bp.route("/push-devices", methods=["POST"])
def register_push_device():
    payload = request.get_json(silent=True) or {}
    user = current_user if getattr(current_user, "is_authenticated", False) else None
    if user is None:
        return jsonify({"ok": False, "message": "Login required."}), 401

    device_token = (payload.get("device_token") or "").strip()
    if not device_token:
        return jsonify({"ok": False, "message": "device_token is required."}), 400

    device = PushDevice.query.filter_by(device_token=device_token).first()
    if device is None:
        device = PushDevice(device_token=device_token, user_id=user.id, portal_role=payload.get("portal_role") or user.role)
        db.session.add(device)
    device.user_id = user.id
    device.portal_role = (payload.get("portal_role") or user.role or "customer").strip().lower()
    device.platform = (payload.get("platform") or "web").strip().lower()
    device.is_active = True
    db.session.commit()
    return jsonify({"ok": True, "device_id": device.id})


@api_v2_bp.route("/sync/flush", methods=["POST"])
def sync_flush():
    if not getattr(current_user, "is_authenticated", False) or not has_role(
        current_user, *ADMIN_PORTAL_ROLES, "delivery"
    ):
        return jsonify({"ok": False, "message": "Access denied."}), 403
    result = get_container().offline_sync_service.flush_pending_actions()
    return jsonify({"ok": True, "result": result})


@api_v2_bp.route("/sync/status")
def sync_status():
    if not getattr(current_user, "is_authenticated", False) or not has_role(
        current_user, *ADMIN_PORTAL_ROLES, "delivery"
    ):
        return jsonify({"ok": False, "message": "Access denied."}), 403
    sync_service = get_container().offline_sync_service
    return jsonify(
        {
            "ok": True,
            "enabled": sync_service.enabled,
            "online": sync_service.is_online() if sync_service.enabled else True,
            "pending_actions": len(sync_service.pending_actions(limit=100)) if sync_service.enabled else 0,
        }
    )


@api_v2_bp.route("/orders/<int:order_id>/qr")
def order_qr(order_id):
    order = Order.query.get_or_404(order_id)
    if not getattr(current_user, "is_authenticated", False):
        return jsonify({"ok": False, "message": "Login required."}), 401
    if current_user.id != order.user_id and not has_role(current_user, *ADMIN_PORTAL_ROLES, "delivery"):
        return jsonify({"ok": False, "message": "Access denied."}), 403

    verification_url = request.url_root.rstrip("/") + "/api/v2/qr/verify"
    data_uri = get_container().qr_service.build_order_qr_data_uri(order, verification_url)
    db.session.commit()
    return jsonify(
        {
            "ok": True,
            "token": order.qr_token,
            "qr_image": data_uri,
            "verification_url": f"{verification_url}?token={order.qr_token}",
        }
    )
