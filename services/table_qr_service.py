import base64
import io
import secrets
from datetime import timedelta

from flask import current_app, url_for

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None

from clock import utcnow
from exceptions import ValidationError
from models import DiningArea, DiningTable, TableMenuScan, TableMenuSession, db


ACTIVE_TABLE_STATUSES = {"active", "available", "occupied"}
TABLE_STATUSES = {
    "active",
    "inactive",
    "occupied",
    "available",
    "temporarily_unavailable",
}


class TableQRService:
    def __init__(self, config):
        self.config = config

    def new_token(self):
        return secrets.token_urlsafe(48)

    def create_area(self, *, branch_id, name):
        name = (name or "").strip()
        if not branch_id or not name:
            raise ValidationError("Branch and dining area name are required.")
        area = DiningArea.query.filter_by(branch_id=branch_id, name=name).first()
        if area:
            area.is_active = True
            return area
        area = DiningArea(branch_id=branch_id, name=name)
        db.session.add(area)
        return area

    def create_table(
        self,
        *,
        branch_id,
        table_number,
        display_name=None,
        area_id=None,
        seating_capacity=2,
        notes=None,
    ):
        table_number = (table_number or "").strip().upper()
        display_name = (display_name or table_number).strip()
        if not branch_id or not table_number:
            raise ValidationError("Branch and table number are required.")
        existing = DiningTable.query.filter_by(
            branch_id=branch_id,
            table_number=table_number,
        ).first()
        if existing:
            raise ValidationError("That table already exists for this branch.")
        table = DiningTable(
            branch_id=branch_id,
            area_id=area_id,
            table_number=table_number,
            display_name=display_name,
            seating_capacity=max(1, int(seating_capacity or 2)),
            qr_token=self.new_token(),
            notes=(notes or "").strip(),
        )
        db.session.add(table)
        return table

    def regenerate_token(self, table):
        table.qr_token = self.new_token()
        table.last_regenerated_at = utcnow()
        table.updated_at = utcnow()
        table.menu_sessions.update({"status": "revoked"})
        return table

    def table_url(self, table, *, external=True):
        kwargs = {"token": table.qr_token, "_external": external}
        if external:
            kwargs["_scheme"] = self.config.get("PREFERRED_URL_SCHEME", "https")
        return url_for("customer.table_menu", **kwargs)

    def build_qr_data_uri(self, table):
        if qrcode is None:
            return ""
        image = qrcode.make(self.table_url(table))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def validate_token(self, token):
        table = DiningTable.query.filter_by(qr_token=(token or "").strip()).first()
        if table is None:
            raise ValidationError("This QR code is invalid or has expired.")
        status = (table.status or "").strip().lower()
        if status not in ACTIVE_TABLE_STATUSES:
            raise ValidationError("This table is not available for QR ordering right now.")
        branch = table.branch
        if branch and getattr(branch, "is_active", True) is False:
            raise ValidationError("This branch is not available for QR ordering right now.")
        return table

    def open_session(self, table, *, user_id=None):
        ttl_minutes = int(self.config.get("TABLE_QR_SESSION_TTL_MINUTES", 180))
        session = TableMenuSession(
            session_token=secrets.token_urlsafe(48),
            table_id=table.id,
            branch_id=table.branch_id,
            user_id=user_id,
            expires_at=utcnow() + timedelta(minutes=max(15, ttl_minutes)),
        )
        db.session.add(session)
        db.session.flush()
        return session

    def validate_session(self, session_token):
        session = TableMenuSession.query.filter_by(
            session_token=(session_token or "").strip(),
            status="active",
        ).first()
        if session is None or session.expires_at <= utcnow():
            if session:
                session.status = "expired"
            raise ValidationError("Please scan the table QR code again before checkout.")
        self.validate_token(session.table.qr_token)
        session.last_seen_at = utcnow()
        return session

    def record_scan(self, table, menu_session, *, ip_address=None, user_agent=None):
        scan = TableMenuScan(
            table_id=table.id,
            branch_id=table.branch_id,
            session_token=menu_session.session_token,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:200],
        )
        db.session.add(scan)
        return scan
