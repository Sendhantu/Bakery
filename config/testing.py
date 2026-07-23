from .base import BaseConfig
import base64


class TestingConfig(BaseConfig):
    ENV = "testing"
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    FORCE_HTTPS = False
    SHOW_DEMO_ACCOUNTS = True
    SOCKETIO_ASYNC_MODE = "threading"
    ENABLE_PORTAL_SIDECARS = False
    ENABLE_LOCAL_SYNC_WORKER = False
    FINANCIAL_DATA_ENCRYPTION_KEY = base64.urlsafe_b64encode(
        b"0123456789abcdef0123456789abcdef"
    ).decode("utf-8")
    ALLOW_DEV_FINANCIAL_KEY_DERIVATION = False
