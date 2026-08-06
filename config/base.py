import os
import secrets
from decimal import Decimal

from .utils import (
    BASE_DIR,
    build_database_uri,
    build_engine_options,
    build_redis_client_options,
    env_flag,
)

try:  # pragma: no cover
    import redis as _redis  # noqa: F401

    REDIS_CLIENT_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_CLIENT_AVAILABLE = False


class BaseConfig:
    ENV = "base"
    DEBUG = False
    TESTING = False
    AUTO_INIT_DB = False
    SHOW_DEMO_ACCOUNTS = False
    DEVELOPMENT_CREDENTIALS_ENABLED = env_flag(
        "DEVELOPMENT_CREDENTIALS_ENABLED", default=False
    )
    MIGRATIONS_ENABLED = True

    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or SECRET_KEY

    SQLALCHEMY_DATABASE_URI = build_database_uri(allow_sqlite_fallback=True)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = build_engine_options(SQLALCHEMY_DATABASE_URI)
    READ_REPLICA_URLS = [
        url.strip()
        for url in os.environ.get("DATABASE_READ_REPLICAS", "").split(",")
        if url.strip()
    ]

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 30
    SESSION_REFRESH_EACH_REQUEST = True
    LOGIN_SESSION_PROTECTION = (
        os.environ.get("LOGIN_SESSION_PROTECTION", "basic").strip().lower() or "basic"
    )

    PREFERRED_URL_SCHEME = "https"
    USE_PROXY_FIX = env_flag("USE_PROXY_FIX", default=False)
    FORCE_HTTPS = env_flag("FORCE_HTTPS", default=True)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    WTF_CSRF_SSL_STRICT = True
    BCRYPT_LOG_ROUNDS = int(os.environ.get("BCRYPT_LOG_ROUNDS", 12))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}

    REDIS_URL = (os.environ.get("REDIS_URL") or "").strip()
    SOCKETIO_MESSAGE_QUEUE = (
        os.environ.get("SOCKETIO_MESSAGE_QUEUE") or REDIS_URL or None
    )
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL or None
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL or None
    CELERY_BEAT_SCHEDULE = {
        "inventory-forecasts-nightly": {
            "task": "tasks.operations.build_inventory_forecasts",
            "schedule": 60 * 60 * 6,
        },
        "subscription-order-generator": {
            "task": "tasks.operations.generate_subscription_orders",
            "schedule": 60 * 60 * 24,
        },
        "offline-sync-retry": {
            "task": "tasks.operations.retry_offline_sync_actions",
            "schedule": 60,
        },
        "queue-metrics-capture": {
            "task": "tasks.operations.capture_queue_metrics",
            "schedule": 60 * 5,
        },
        "backup-health-verification": {
            "task": "tasks.operations.verify_backup_health",
            "schedule": 60 * 60 * 12,
        },
        "analytics-aggregate": {
            "task": "tasks.operations.aggregate_analytics_snapshot",
            "schedule": 60 * 30,
        },
        "weather-forecast-refresh": {
            "task": "tasks.operations.refresh_weather_forecast",
            "schedule": 60 * 60 * 6,
        },
        "birthday-loyalty-rewards": {
            "task": "tasks.operations.process_birthday_rewards",
            "schedule": 60 * 60 * 24,
        },
        "abandoned-cart-reminders": {
            "task": "tasks.operations.send_abandoned_cart_reminders",
            "schedule": 60 * 60 * 2,
        },
    }
    RATELIMIT_STORAGE_URI = (
        os.environ.get("RATELIMIT_STORAGE_URI") or REDIS_URL or "memory://"
    )
    CACHE_TYPE = "RedisCache" if REDIS_URL and REDIS_CLIENT_AVAILABLE else "SimpleCache"
    CACHE_REDIS_URL = REDIS_URL or None
    CACHE_OPTIONS = build_redis_client_options() if REDIS_URL else {}
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get("CACHE_DEFAULT_TIMEOUT", 300))
    REDIS_CLIENT_OPTIONS = build_redis_client_options()

    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.environ.get("SOCKETIO_CORS_ALLOWED_ORIGINS", "*")

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = env_flag("MAIL_USE_TLS", default=True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", "SweetCrumbs <noreply@sweetcrumbs.com>"
    )
    MAIL_ENABLED = bool(MAIL_USERNAME)

    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")
    SMS_ENABLED = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)
    WHATSAPP_ENABLED = bool(
        TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM
    )

    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")
    PRODUCT_IMAGE_FOLDER = os.environ.get(
        "PRODUCT_IMAGE_FOLDER", "sweetcrumbs/products"
    )

    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    SLOW_QUERY_THRESHOLD_MS = int(os.environ.get("SLOW_QUERY_THRESHOLD_MS", 250))

    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    ROUTE_CACHE_TTL_SECONDS = int(os.environ.get("ROUTE_CACHE_TTL_SECONDS", 900))
    OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
    WEATHER_API_URL = os.environ.get(
        "WEATHER_API_URL",
        "https://api.openweathermap.org/data/2.5/forecast",
    )
    WEATHER_FORECAST_TTL_SECONDS = int(
        os.environ.get("WEATHER_FORECAST_TTL_SECONDS", 60 * 60 * 6)
    )
    WEATHER_REQUEST_TIMEOUT_SECONDS = int(
        os.environ.get("WEATHER_REQUEST_TIMEOUT_SECONDS", 5)
    )
    STORE_LATITUDE = os.environ.get("STORE_LATITUDE", "").strip()
    STORE_LONGITUDE = os.environ.get("STORE_LONGITUDE", "").strip()
    STORE_COUNTRY_CODE = os.environ.get("STORE_COUNTRY_CODE", "IN").strip() or "IN"
    HOT_DAY_THRESHOLD_C = float(os.environ.get("HOT_DAY_THRESHOLD_C", "35"))
    DEMAND_MIN_HISTORY_DAYS = int(os.environ.get("DEMAND_MIN_HISTORY_DAYS", 21))
    DEMAND_MIN_MATCHING_DAYS = int(os.environ.get("DEMAND_MIN_MATCHING_DAYS", 3))
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")
    OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "3"))
    DEMAND_USE_OLLAMA = env_flag("DEMAND_USE_OLLAMA", default=False)
    AI_ASSISTANT_ENABLED = env_flag("AI_ASSISTANT_ENABLED", default=False)
    AI_SUPPORT_BOT_ENABLED = env_flag("AI_SUPPORT_BOT_ENABLED", default=False)
    AI_PUSH_RECOMMENDATIONS_ENABLED = env_flag(
        "AI_PUSH_RECOMMENDATIONS_ENABLED", default=False
    )
    AI_CONTEXT_WINDOW_DAYS = int(os.environ.get("AI_CONTEXT_WINDOW_DAYS", "90"))
    AI_CONTEXT_PRODUCT_LIMIT = int(os.environ.get("AI_CONTEXT_PRODUCT_LIMIT", "8"))
    AI_OFFERS_ENABLED = env_flag("AI_OFFERS_ENABLED", default=False)
    AI_OFFERS_PROVIDER = os.environ.get("AI_OFFERS_PROVIDER", "").strip()
    AI_OFFERS_MODEL = os.environ.get("AI_OFFERS_MODEL", "").strip()
    AI_OFFERS_LOOKBACK_DAYS = int(os.environ.get("AI_OFFERS_LOOKBACK_DAYS", "30"))
    AI_OFFERS_HORIZON_DAYS = int(os.environ.get("AI_OFFERS_HORIZON_DAYS", "7"))

    FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "")
    FIREBASE_CLIENT_EMAIL = os.environ.get("FIREBASE_CLIENT_EMAIL", "")
    FIREBASE_PRIVATE_KEY = os.environ.get("FIREBASE_PRIVATE_KEY", "").replace(
        "\\n", "\n"
    )

    FCM_ENABLED = bool(
        FIREBASE_PROJECT_ID and FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY
    )

    DEFAULT_BRANCH_ID = int(os.environ.get("DEFAULT_BRANCH_ID", "1") or 1)

    FINANCIAL_DATA_ENCRYPTION_KEY = os.environ.get("FINANCIAL_DATA_ENCRYPTION_KEY", "")
    ALLOW_DEV_FINANCIAL_KEY_DERIVATION = env_flag(
        "ALLOW_DEV_FINANCIAL_KEY_DERIVATION", default=True
    )

    OFFLINE_SYNC_ENABLED = env_flag("OFFLINE_SYNC_ENABLED", default=True)
    OFFLINE_SYNC_DB_TEMPLATE = str(
        BASE_DIR / "instance" / "offline" / "{portal_role}_offline_sync.sqlite"
    )
    OFFLINE_CACHE_MAX_AGE_SECONDS = int(
        os.environ.get("OFFLINE_CACHE_MAX_AGE_SECONDS", 86400)
    )
    SYNC_RETRY_INTERVAL_SECONDS = int(os.environ.get("SYNC_RETRY_INTERVAL_SECONDS", 30))
    SYNC_BATCH_SIZE = int(os.environ.get("SYNC_BATCH_SIZE", 50))
    ENABLE_LOCAL_SYNC_WORKER = env_flag("ENABLE_LOCAL_SYNC_WORKER", default=True)
    ENABLE_PORTAL_SIDECARS = env_flag("ENABLE_PORTAL_SIDECARS", default=True)

    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "frame-src 'self' https://www.google.com https://maps.google.com; "
        "connect-src 'self' https: wss: ws:; "
        "object-src 'none'; "
        "upgrade-insecure-requests"
    )
    ALLOW_GEOLOCATION = True

    BAKERY_NAME = os.environ.get("BAKERY_NAME", "Sweet Crumbs Bakery")
    SITE_META_DESCRIPTION = (
        "Artisan cakes, pastries, breads, subscriptions, and delivery operations "
        "managed from one hybrid bakery platform."
    )
    STORE_DETAILS = {
        "name": os.environ.get("STORE_NAME", "SweetCrumbs Studio Bakery"),
        "gstin": os.environ.get("STORE_GSTIN", "").strip().upper(),
        "address_line1": os.environ.get("STORE_ADDRESS_LINE1", "12 Baker Street"),
        "address_line2": os.environ.get("STORE_ADDRESS_LINE2", "RS Puram"),
        "city": os.environ.get("STORE_CITY", "Coimbatore"),
        "pincode": os.environ.get("STORE_PINCODE", "641002"),
        "phone": os.environ.get("STORE_PHONE", "+91 99999 99999"),
        "phone_tel": os.environ.get("STORE_PHONE_TEL", "+919999999999"),
        "hours": os.environ.get("STORE_HOURS", "Open daily, 9:00 AM - 9:00 PM"),
        "instagram_url": os.environ.get("BAKERY_INSTAGRAM_URL", "").strip(),
        "facebook_url": os.environ.get("BAKERY_FACEBOOK_URL", "").strip(),
    }
    TIME_SLOTS = [
        "09:00 - 11:00",
        "11:00 - 13:00",
        "13:00 - 15:00",
        "15:00 - 17:00",
        "17:00 - 19:00",
        "19:00 - 21:00",
    ]
    PICKUP_BUFFER_MINUTES = int(os.environ.get("PICKUP_BUFFER_MINUTES", 20))
    DELIVERY_FREE_THRESHOLD = int(os.environ.get("DELIVERY_FREE_THRESHOLD", 500))
    DELIVERY_CHARGE = int(os.environ.get("DELIVERY_CHARGE", 50))
    GST_RESTAURANT_SERVICE_NO_ITC = (
        os.environ.get("GST_RESTAURANT_SERVICE_NO_ITC", "true").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    GST_ECOMMERCE_TCS_RATE = Decimal(
        os.environ.get("GST_ECOMMERCE_TCS_RATE", "1")
    )

    LOYALTY_EARN_RATE = int(os.environ.get("LOYALTY_EARN_RATE", 1))
    LOYALTY_EARN_PER = int(os.environ.get("LOYALTY_EARN_PER", 10))
    LOYALTY_REDEEM_RATE = int(os.environ.get("LOYALTY_REDEEM_RATE", 10))
    LOYALTY_REDEEM_PER = int(os.environ.get("LOYALTY_REDEEM_PER", 10))
    LOYALTY_REDEEM_MAX_PERCENT = int(
        os.environ.get("LOYALTY_REDEEM_MAX_PERCENT", 20)
    )
    LOYALTY_MIN_REDEEM_ORDER_VALUE = int(
        os.environ.get("LOYALTY_MIN_REDEEM_ORDER_VALUE", 500)
    )
    LOYALTY_MIN_REDEEM_PERCENT = int(
        os.environ.get("LOYALTY_MIN_REDEEM_PERCENT", 10)
    )
    LOYALTY_EXPIRY_DAYS = int(os.environ.get("LOYALTY_EXPIRY_DAYS", 365))

    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", 5))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", 15))

    FEATURE_FLAGS = {
        "api.v2.enabled": True,
        "events.enabled": True,
        "orders.service_layer": True,
        "offline.sync.enabled": True,
        "pwa.enabled": True,
        "forecasting.enabled": True,
        "dynamic_pricing.enabled": True,
        "pos.enabled": True,
        "kds.enabled": True,
    }
    ENABLED_PLUGINS = []
    API_VERSIONS = ("v1", "v2")
    PROVIDER_REGISTRY = {
        "sms": "twilio",
        "email": "flask_mail",
        "payment": "internal_state_machine",
        "maps": "google_maps",
        "storage": "cloudinary",
        "notifications": "multi_channel",
        "authentication": "session_and_jwt",
    }

    @classmethod
    def init_app(cls, app):
        return None
