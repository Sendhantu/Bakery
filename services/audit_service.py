from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Union

from flask import has_request_context, request

from models import AuditLog, OperationalAlert, db

SENSITIVE_FIELD_KEYS = frozenset(
    {
        "amount",
        "tax_amount",
        "tds_withheld",
        "description",
        "counterparty",
        "password",
        "gateway_payload",
        "amount_collected",
        "total",
        "subtotal",
        "cost_per_unit",
    }
)
ENCRYPTED_ENTITY_TYPES = frozenset({"FinancialTransaction"})


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _redacted_indicator(field_name: str, entity_type: Optional[str] = None) -> Dict[str, str]:
    if entity_type in ENCRYPTED_ENTITY_TYPES or field_name in {
        "amount",
        "tax_amount",
        "tds_withheld",
        "description",
        "counterparty",
    }:
        return {"_redacted": "encrypted_or_sensitive_financial_field", "field": field_name}
    return {"_redacted": "sensitive_field", "field": field_name}


def _sanitize_payload(
    payload: Optional[Any],
    entity_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return {"value": payload if not isinstance(payload, dict) else "..."}

    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        key_lower = str(key).lower()
        if key_lower in SENSITIVE_FIELD_KEYS or (
            entity_type in ENCRYPTED_ENTITY_TYPES and key_lower in {"amount", "tax_amount", "tds_withheld", "description", "counterparty"}
        ):
            if value is not None and value != "":
                sanitized[key] = {**_redacted_indicator(key_lower, entity_type), "changed": True}
            else:
                sanitized[key] = None
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_payload(value, entity_type)
        else:
            sanitized[key] = value
    return sanitized


def _resolve_actor_id(actor) -> Optional[int]:
    if actor is None:
        return None
    if isinstance(actor, int):
        return actor
    return getattr(actor, "id", None)


def _client_ip() -> Optional[str]:
    if not has_request_context():
        return None
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr


class AuditService:
    def already_processed(self, request_id):
        if not request_id:
            return False
        return (
            AuditLog.query.filter_by(request_id=request_id).with_entities(AuditLog.id).first()
            is not None
        )

    def log(
        self,
        actor,
        action: str,
        target_type: str,
        target_id,
        before=None,
        after=None,
        *,
        branch_id=None,
        request_id=None,
        ip_address=None,
        change_summary: str = "",
        metadata=None,
    ) -> str:
        """Write-once audit entry. Sensitive/financial fields are redacted in before/after JSON."""
        request_id = request_id or str(uuid.uuid4())
        if self.already_processed(request_id):
            return request_id

        entity_type = (target_type or "").strip() or "Unknown"
        before_payload = _sanitize_payload(before, entity_type)
        after_payload = _sanitize_payload(after, entity_type)

        legacy_metadata = dict(metadata or {})
        if before_payload is not None:
            legacy_metadata.setdefault("before", before_payload)
        if after_payload is not None:
            legacy_metadata.setdefault("after", after_payload)

        db.session.add(
            AuditLog(
                request_id=request_id,
                actor_id=_resolve_actor_id(actor),
                branch_id=branch_id,
                entity_type=entity_type,
                entity_id=str(target_id),
                action=(action or "").strip(),
                change_summary=change_summary,
                before_value=json.dumps(before_payload, default=_json_default, sort_keys=True)
                if before_payload is not None
                else None,
                after_value=json.dumps(after_payload, default=_json_default, sort_keys=True)
                if after_payload is not None
                else None,
                ip_address=ip_address if ip_address is not None else _client_ip(),
                metadata_json=json.dumps(legacy_metadata, default=_json_default, sort_keys=True),
            )
        )
        return request_id

    def record(
        self,
        action,
        entity_type,
        entity_id,
        *,
        actor_id=None,
        branch_id=None,
        request_id=None,
        metadata=None,
        change_summary="",
        before=None,
        after=None,
        ip_address=None,
    ):
        """Backward-compatible wrapper around log()."""
        return self.log(
            actor_id,
            action,
            entity_type,
            entity_id,
            before=before or (metadata or {}).get("before"),
            after=after or (metadata or {}).get("after") or {
                k: v for k, v in (metadata or {}).items() if k not in {"before", "after"}
            }
            or None,
            branch_id=branch_id,
            request_id=request_id,
            ip_address=ip_address,
            change_summary=change_summary,
            metadata=metadata,
        )

    def query_logs(
        self,
        *,
        actor_id=None,
        action=None,
        start_date=None,
        end_date=None,
        limit=200,
    ):
        from datetime import datetime, time, timedelta

        from services.analytics_service import _exclusive_end, _parse_date

        query = AuditLog.query
        if actor_id:
            query = query.filter(AuditLog.actor_id == actor_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if start_date:
            start = _parse_date(start_date)
            query = query.filter(AuditLog.created_at >= start)
        if end_date:
            end = _exclusive_end(end_date)
            query = query.filter(AuditLog.created_at < end)
        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    def distinct_actions(self, limit=100):
        rows = (
            db.session.query(AuditLog.action)
            .distinct()
            .order_by(AuditLog.action.asc())
            .limit(limit)
            .all()
        )
        return [row[0] for row in rows if row[0]]

    def alert(
        self,
        alert_type,
        title,
        message,
        *,
        severity="warning",
        user_id=None,
        branch_id=None,
    ):
        db.session.add(
            OperationalAlert(
                alert_type=alert_type,
                title=title,
                message=message,
                severity=severity,
                user_id=user_id,
                branch_id=branch_id,
            )
        )
