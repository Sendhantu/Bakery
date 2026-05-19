from .base import BaseConfig
from .utils import (
    ensure_instance_dirs,
    forbid_sqlite_in_production,
    reject_weak_secret_key,
    require_database_config,
    require_env_vars,
)


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    SHOW_DEMO_ACCOUNTS = False
    SOCKETIO_ASYNC_MODE = "gevent"
    CACHE_TYPE = "RedisCache"

    @classmethod
    def init_app(cls, app):
        ensure_instance_dirs()
        require_database_config()
        require_env_vars(
            [
                "REDIS_URL",
                "SECRET_KEY",
                "JWT_SECRET_KEY",
                "CLOUDINARY_CLOUD_NAME",
                "CLOUDINARY_API_KEY",
                "CLOUDINARY_API_SECRET",
            ]
        )
        reject_weak_secret_key(app.config.get("SECRET_KEY"), cls.ENV)
        forbid_sqlite_in_production(app.config.get("SQLALCHEMY_DATABASE_URI"), cls.ENV)

        if not app.config.get("RATELIMIT_STORAGE_URI") or app.config[
            "RATELIMIT_STORAGE_URI"
        ] == "memory://":
            raise RuntimeError("RATELIMIT_STORAGE_URI or REDIS_URL required in production")
        if not app.config.get("SOCKETIO_MESSAGE_QUEUE"):
            raise RuntimeError("SOCKETIO_MESSAGE_QUEUE or REDIS_URL required in production")
        if not app.config.get("CELERY_BROKER_URL") or not app.config.get(
            "CELERY_RESULT_BACKEND"
        ):
            raise RuntimeError("CELERY_BROKER_URL and CELERY_RESULT_BACKEND required in production")
