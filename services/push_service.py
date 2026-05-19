import json
import logging

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self, config):
        self.enabled = bool(config.get("FCM_ENABLED"))
        self.credentials_json = (config.get("FIREBASE_CREDENTIALS_JSON") or "").strip()
        if not self.credentials_json and self.enabled:
            self.credentials_json = json.dumps(
                {
                    "type": "service_account",
                    "project_id": config.get("FIREBASE_PROJECT_ID"),
                    "client_email": config.get("FIREBASE_CLIENT_EMAIL"),
                    "private_key": config.get("FIREBASE_PRIVATE_KEY"),
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        self._client = None

    def _get_client(self):
        if not self.enabled or not self.credentials_json:
            return None
        if self._client is not None:
            return self._client
        try:
            import firebase_admin
            from firebase_admin import credentials

            if not firebase_admin._apps:
                cred = credentials.Certificate(json.loads(self.credentials_json))
                firebase_admin.initialize_app(cred)
            from firebase_admin import messaging

            self._client = messaging
            return messaging
        except Exception:
            logger.exception("fcm_client_init_failed")
            return None

    def send_to_user(self, user_id, title, body, data=None):
        from models import PushDevice, db

        devices = PushDevice.query.filter_by(user_id=user_id, is_active=True).all()
        if not devices:
            return 0
        sent = 0
        for device in devices:
            if self.send_to_token(device.device_token, title, body, data=data):
                sent += 1
        db.session.commit()
        return sent

    def send_to_token(self, token, title, body, data=None):
        messaging = self._get_client()
        if messaging is None or not token:
            return False
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data={key: str(value) for key, value in (data or {}).items()},
                token=token,
            )
            messaging.send(message)
            return True
        except Exception:
            logger.exception("fcm_send_failed")
            return False
