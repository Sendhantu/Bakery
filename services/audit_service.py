import json
import uuid

from models import AuditLog, OperationalAlert, db


class AuditService:
    def already_processed(self, request_id):
        if not request_id:
            return False
        return (
            AuditLog.query.filter_by(request_id=request_id).with_entities(AuditLog.id).first()
            is not None
        )

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
    ):
        request_id = request_id or str(uuid.uuid4())
        if self.already_processed(request_id):
            return request_id

        db.session.add(
            AuditLog(
                request_id=request_id,
                actor_id=actor_id,
                branch_id=branch_id,
                entity_type=entity_type,
                entity_id=str(entity_id),
                action=action,
                change_summary=change_summary,
                metadata_json=json.dumps(metadata or {}, sort_keys=True),
            )
        )
        return request_id

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
