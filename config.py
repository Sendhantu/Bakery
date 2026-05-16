import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
DEFAULT_SQLITE_PATH = os.path.join(BASE_DIR, "bakery.db")


class Config:
    # ── Core ───────────────────────────────────────────
    SECRET_KEY = os.environ.get(
        "SECRET_KEY", "bakery-secret-key-2024-change-in-production"
    )
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        os.environ.get(
            "MYSQL_DATABASE_URL",
            f"sqlite:///{DEFAULT_SQLITE_PATH}"
        ),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # auto-reconnect on stale connections
        "pool_recycle": 300,
    }
    READ_REPLICA_URLS = [
        url.strip()
        for url in os.environ.get("DATABASE_READ_REPLICAS", "").split(",")
        if url.strip()
    ]

    # ── Uploads ────────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images", "products")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB (was 16 MB — tightened)
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}

    # ── CSRF (Flask-WTF) ───────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour token validity

    # ── Session / Cookie security ──────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 30  # 30 days

    # ── Application hardening ──────────────────────────
    PREFERRED_URL_SCHEME = "https"
    WTF_CSRF_SSL_STRICT = True
    BCRYPT_LOG_ROUNDS = int(os.environ.get("BCRYPT_LOG_ROUNDS", 12))
    SESSION_REFRESH_EACH_REQUEST = True
    USE_PROXY_FIX = os.environ.get("USE_PROXY_FIX", "false").strip().lower() in {"1", "true", "yes", "on"}
    RATELIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://images.unsplash.com; "
        "frame-src 'self' https://www.google.com https://maps.google.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "upgrade-insecure-requests"
    )
    ALLOW_GEOLOCATION = True

    # ── Business config ────────────────────────────────
    BAKERY_NAME = "Sweet Crumbs Bakery"
    SITE_META_DESCRIPTION = (
        "Artisan cakes, pastries, and breads baked fresh daily. "
        "Delivery in Coimbatore — birthday cakes, wedding tiers, eggless options."
    )
    CANCELLATION_WINDOW_MINUTES = 2
    MAX_ADDRESS_CHANGES = 2
    TIME_SLOTS = [
        "09:00 - 11:00",
        "11:00 - 13:00",
        "13:00 - 15:00",
        "15:00 - 17:00",
        "17:00 - 19:00",
        "19:00 - 21:00",
    ]
    PICKUP_BUFFER_MINUTES = 20
    STORE_DETAILS = {
        "name": "SweetCrumbs Studio Bakery",
        "address_line1": "12 Baker Street",
        "address_line2": "RS Puram",
        "city": "Coimbatore",
        "pincode": "641002",
        "phone": "+91 99999 99999",
        # E.164-style digits for tel: href (no spaces)
        "phone_tel": "+919999999999",
        "hours": "Open daily, 9:00 AM – 9:00 PM",
        # Optional — leave empty to hide footer social icons
        "instagram_url": os.environ.get("BAKERY_INSTAGRAM_URL", "").strip(),
        "facebook_url": os.environ.get("BAKERY_FACEBOOK_URL", "").strip(),
    }

    # ── Email (Flask-Mail) ─────────────────────────────
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")  # set in .env
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")  # set in .env
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", "SweetCrumbs <noreply@sweetcrumbs.com>"
    )
    MAIL_ENABLED = bool(
        os.environ.get("MAIL_USERNAME")
    )  # auto-disable if not configured

    # ── SMS (Twilio stub) ──────────────────────────────
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
    SMS_ENABLED = bool(os.environ.get("TWILIO_ACCOUNT_SID"))

    # ── Async / Queue ──────────────────────────────────
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
    SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE")

    # ── Loyalty / Rewards ──────────────────────────────
    LOYALTY_EARN_RATE = 1  # points earned per LOYALTY_EARN_PER rupees
    LOYALTY_EARN_PER = 10  # ₹10 = 1 point
    LOYALTY_REDEEM_RATE = 10  # ₹ discount per LOYALTY_REDEEM_PER points
    LOYALTY_REDEEM_PER = 100  # 100 points minimum to redeem
    LOYALTY_EXPIRY_DAYS = 365  # points expire after N days

    # ── Rate limiting (for login brute-force) ──────────
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCKOUT_MINUTES = 15

    # ── Feature Flags / Modular Config ─────────────────
    FEATURE_FLAGS = {
        "auth.admin_2fa_provision": False,
        "api.v2.enabled": True,
        "plugins.enabled": True,
        "events.enabled": True,
        "orders.service_layer": True,
    }
    ENABLED_PLUGINS = []
    API_VERSIONS = ("v1", "v2")
    AUTH_ADMIN_2FA_PROVISION_ENABLED = False
    AUTH_ADMIN_2FA_PROVIDERS = []
    AUTH_ADMIN_2FA_ENFORCEMENT = "off"
    PROVIDER_REGISTRY = {
        "sms": "twilio",
        "email": "flask_mail",
        "payment": "demo",
        "maps": "google_maps",
        "storage": "local",
        "notifications": "in_app",
        "authentication": "local",
    }
    MIGRATIONS_ENABLED = True


class DevelopmentConfig(Config):
    ENV = "development"
    DEBUG = True
    AUTO_INIT_DB = True
    # In dev, relax cookie/csrf security so http://localhost works
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    WTF_CSRF_SSL_STRICT = False


class TestingConfig(Config):
    ENV = "testing"
    """Used by automated tests (in-memory DB, no CSRF for simpler client tests)."""
    TESTING = True
    DEBUG = True
    AUTO_INIT_DB = False
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    ENV = "production"
    DEBUG = False
    AUTO_INIT_DB = False
    SESSION_COOKIE_SECURE = True  # enforce HTTPS-only cookies
    REMEMBER_COOKIE_SECURE = True

    @classmethod
    def init_app(cls, app):
        # Warn loudly if secret key is still the default
        if app.config["SECRET_KEY"] == "bakery-secret-key-2024-change-in-production":
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random value in production. "
                "Set the SECRET_KEY environment variable."
            )


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
