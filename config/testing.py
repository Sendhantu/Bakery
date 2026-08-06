from .base import BaseConfig
import base64
from .utils import build_database_uri, build_engine_options


class TestingConfig(BaseConfig):
    ENV = "testing"
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    FORCE_HTTPS = False
    SHOW_DEMO_ACCOUNTS = True
    REDIS_URL = ""
    SOCKETIO_MESSAGE_QUEUE = None
    CELERY_BROKER_URL = None
    CELERY_RESULT_BACKEND = None
    RATELIMIT_STORAGE_URI = "memory://"
    CACHE_TYPE = "SimpleCache"
    CACHE_REDIS_URL = None
    CACHE_OPTIONS = {}
    AI_ASSISTANT_ENABLED = False
    AI_SUPPORT_BOT_ENABLED = False
    AI_PUSH_RECOMMENDATIONS_ENABLED = False
    SOCKETIO_ASYNC_MODE = "threading"
    ENABLE_PORTAL_SIDECARS = False
    ENABLE_LOCAL_SYNC_WORKER = False
    FINANCIAL_DATA_ENCRYPTION_KEY = base64.urlsafe_b64encode(
        b"0123456789abcdef0123456789abcdef"
    ).decode("utf-8")
    ALLOW_DEV_FINANCIAL_KEY_DERIVATION = False

    @classmethod
    def init_app(cls, app):
        database_uri = build_database_uri(allow_sqlite_fallback=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = build_engine_options(database_uri)
