import os

from .base import BaseConfig
from .utils import (
    ensure_instance_dirs,
    env_flag,
    forbid_sqlite_in_production,
    is_vercel_environment,
    reject_weak_secret_key,
    require_database_config,
    require_env_vars,
)


VERCEL_DEPLOYMENT = is_vercel_environment()


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    SHOW_DEMO_ACCOUNTS = False
    USE_PROXY_FIX = env_flag("USE_PROXY_FIX", default=True)
    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "gevent")
    CACHE_TYPE = "RedisCache"
    REDIS_REQUIRED = True
    SOCKETIO_QUEUE_REQUIRED = True
    CELERY_REQUIRED = True
    STORAGE_REQUIRED = True

    @classmethod
    def init_app(cls, app):
        ensure_instance_dirs()
        require_database_config()
        require_env_vars(
            [
                "DATABASE_URL",
                "REDIS_URL",
                "SOCKETIO_MESSAGE_QUEUE",
                "CELERY_BROKER_URL",
                "CELERY_RESULT_BACKEND",
                "RATELIMIT_STORAGE_URI",
                "SECRET_KEY",
                "JWT_SECRET_KEY",
                "CLOUDINARY_CLOUD_NAME",
                "CLOUDINARY_API_KEY",
                "CLOUDINARY_API_SECRET",
            ]
        )
        app.config["IS_VERCEL"] = VERCEL_DEPLOYMENT
        app.config["REDIS_REQUIRED"] = cls.REDIS_REQUIRED
        app.config["SOCKETIO_QUEUE_REQUIRED"] = cls.SOCKETIO_QUEUE_REQUIRED
        app.config["CELERY_REQUIRED"] = cls.CELERY_REQUIRED
        app.config["STORAGE_REQUIRED"] = cls.STORAGE_REQUIRED
        reject_weak_secret_key(app.config.get("SECRET_KEY"), cls.ENV)
        forbid_sqlite_in_production(app.config.get("SQLALCHEMY_DATABASE_URI"), cls.ENV)
        if not app.config.get("RATELIMIT_STORAGE_URI") or app.config[
            "RATELIMIT_STORAGE_URI"
        ] == "memory://":
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI or REDIS_URL required in production"
            )
