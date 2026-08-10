import hashlib
import hmac
import json
from datetime import timedelta

from flask import has_request_context, request

from clock import utcnow
from exceptions import ValidationError
from models import BackupVerification, SecurityEvent, WebhookEventLog, db


def _client_ip():
    if not has_request_context():
        return None
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr


def _user_agent():
    if not has_request_context():
        return None
    return (request.headers.get("User-Agent") or "")[:200]


class SecurityService:
    def __init__(self, config):
        self.config = config

    def record_event(
        self,
        event_type,
        *,
        severity="warning",
        user_id=None,
        actor_id=None,
        branch_id=None,
        path=None,
        details=None,
    ):
        event = SecurityEvent(
            event_type=(event_type or "").strip()[:80],
            severity=(severity or "warning").strip()[:20],
            user_id=user_id,
            actor_id=actor_id,
            branch_id=branch_id,
            path=(path or (request.path if has_request_context() else "") or "")[:255],
            ip_address=_client_ip(),
            user_agent=_user_agent(),
            details=json.dumps(details or {}, sort_keys=True) if isinstance(details, dict) else details,
        )
        db.session.add(event)
        return event

    def verify_webhook(
        self,
        provider,
        payload,
        signature,
        *,
        event_id,
        event_type=None,
        timestamp=None,
        secret=None,
    ):
        provider = (provider or "").strip().lower()
        event_id = (event_id or "").strip()
        if not provider or not event_id:
            raise ValidationError("Webhook provider and event id are required.")

        payload_bytes = payload if isinstance(payload, bytes) else str(payload or "").encode()
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        existing = WebhookEventLog.query.filter_by(
            provider=provider,
            event_id=event_id,
        ).first()
        if existing:
            existing.replayed = True
            existing.processing_status = "duplicate"
            self.record_event(
                "webhook_replay_blocked",
                severity="warning",
                details={"provider": provider, "event_id": event_id},
            )
            return existing, False

        log = WebhookEventLog(
            provider=provider,
            event_id=event_id,
            event_type=(event_type or "")[:120],
            payload_hash=payload_hash,
            signature_status="pending",
            processing_status="received",
        )
        db.session.add(log)

        resolved_secret = secret or self.config.get(f"{provider.upper()}_WEBHOOK_SECRET", "")
        if not resolved_secret:
            log.signature_status = "missing_secret"
            log.processing_status = "rejected"
            log.error_details = "Webhook secret is not configured."
            self.record_event(
                "webhook_secret_missing",
                severity="high",
                details={"provider": provider, "event_id": event_id},
            )
            return log, False

        if timestamp is not None:
            try:
                sent_at = int(timestamp)
                now = int(utcnow().timestamp())
                tolerance = int(self.config.get("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", 300))
                if abs(now - sent_at) > max(30, tolerance):
                    log.signature_status = "stale_timestamp"
                    log.processing_status = "rejected"
                    self.record_event(
                        "webhook_stale_timestamp",
                        severity="warning",
                        details={"provider": provider, "event_id": event_id},
                    )
                    return log, False
            except (TypeError, ValueError):
                log.signature_status = "invalid_timestamp"
                log.processing_status = "rejected"
                return log, False

        expected = hmac.new(
            resolved_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        provided = (signature or "").replace("sha256=", "").strip()
        if not hmac.compare_digest(expected, provided):
            log.signature_status = "invalid"
            log.processing_status = "rejected"
            self.record_event(
                "webhook_signature_failed",
                severity="high",
                details={"provider": provider, "event_id": event_id},
            )
            return log, False

        log.signature_status = "valid"
        log.processing_status = "verified"
        log.processed_at = utcnow()
        return log, True

    def infrastructure_status(self):
        recent_cutoff = utcnow() - timedelta(hours=24)
        return {
            "force_https": bool(self.config.get("FORCE_HTTPS")),
            "secure_cookies": bool(self.config.get("SESSION_COOKIE_SECURE")),
            "csrf_enabled": bool(self.config.get("WTF_CSRF_ENABLED")),
            "rate_limit_storage": self.config.get("RATELIMIT_STORAGE_URI", ""),
            "csp_enabled": bool(self.config.get("CONTENT_SECURITY_POLICY")),
            "backup_recent": BackupVerification.query.filter(
                BackupVerification.verified_at >= recent_cutoff,
                BackupVerification.status == "verified",
            ).count(),
        }
