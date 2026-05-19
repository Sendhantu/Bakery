from .base import BaseConfig, REDIS_CLIENT_AVAILABLE
from .utils import ensure_instance_dirs


class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = True
    SHOW_DEMO_ACCOUNTS = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False
    FORCE_HTTPS = False
    REDIS_URL = BaseConfig.REDIS_URL or "redis://127.0.0.1:6379/0"
    SOCKETIO_MESSAGE_QUEUE = BaseConfig.SOCKETIO_MESSAGE_QUEUE or REDIS_URL
    CELERY_BROKER_URL = BaseConfig.CELERY_BROKER_URL or REDIS_URL
    CELERY_RESULT_BACKEND = BaseConfig.CELERY_RESULT_BACKEND or REDIS_URL
    RATELIMIT_STORAGE_URI = BaseConfig.RATELIMIT_STORAGE_URI or REDIS_URL
    CACHE_TYPE = "RedisCache" if REDIS_URL and REDIS_CLIENT_AVAILABLE else "SimpleCache"
    CACHE_REDIS_URL = REDIS_URL if REDIS_CLIENT_AVAILABLE else None

    @classmethod
    def init_app(cls, app):
        ensure_instance_dirs()
