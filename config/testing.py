from .base import BaseConfig


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
