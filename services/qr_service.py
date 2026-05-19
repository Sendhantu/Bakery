import base64
import io
import secrets
from datetime import datetime

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None

from exceptions import ValidationError
from models import Order, db


class QRService:
    def ensure_order_token(self, order):
        if not order.qr_token:
            order.qr_token = secrets.token_urlsafe(24)
        return order.qr_token

    def build_order_qr_data_uri(self, order, verification_url):
        if qrcode is None:
            return ""
        payload = f"{verification_url}?token={self.ensure_order_token(order)}"
        image = qrcode.make(payload)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def verify_token(self, token, *, actor_id=None):
        order = Order.query.filter_by(qr_token=(token or "").strip()).first()
        if order is None:
            raise ValidationError("Invalid or expired QR token.")
        if order.qr_verified_at is not None:
            raise ValidationError("This QR code has already been used.")

        order.qr_verified_at = datetime.utcnow()
        order.qr_verified_by = actor_id
        if order.status in {"PACKED", "READY_FOR_PICKUP", "OUT_FOR_DELIVERY"}:
            order.status = "DELIVERED"
            order.mark_status_change()
        db.session.commit()
        return order
