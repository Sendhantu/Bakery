import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
INSTANCE_DIR = BASE_DIR / "instance"
DEFAULT_SQLITE_PATH = BASE_DIR / "bakery.db"


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_vercel_environment():
    return bool(
        (os.environ.get("VERCEL") or "").strip()
        or (os.environ.get("VERCEL_ENV") or "").strip()
        or (os.environ.get("VERCEL_URL") or "").strip()
    )


def normalize_database_uri(database_uri):
    database_uri = (database_uri or "").strip()
    if database_uri.startswith("mysql://"):
        return "mysql+pymysql://" + database_uri[len("mysql://") :]
    if database_uri.startswith("postgres://"):
        return "postgresql+psycopg://" + database_uri[len("postgres://") :]
    if database_uri.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_uri[len("postgresql://") :]
    return database_uri


def build_database_uri(allow_sqlite_fallback=True):
    for env_name in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRES_URL_NON_POOLING",
        "MYSQL_DATABASE_URL",
    ):
        direct_url = normalize_database_uri(os.environ.get(env_name))
        if direct_url:
            return direct_url

    db_host = (os.environ.get("DB_HOST") or "").strip()
    db_scheme = (
        os.environ.get("DB_SCHEME")
        or os.environ.get("DB_DIALECT")
        or os.environ.get("DATABASE_SCHEME")
        or ""
    ).strip().lower()
    postgres_scheme = db_scheme in {
        "postgres",
        "postgresql",
        "postgresql+psycopg",
        "psycopg",
    }
    default_db_port = "5432" if postgres_scheme else "4000"
    db_port = (os.environ.get("DB_PORT") or default_db_port).strip()
    db_user = (os.environ.get("DB_USER") or "").strip()
    db_password = os.environ.get("DB_PASSWORD", "")
    db_name = (os.environ.get("DB_NAME") or "").strip()

    if db_host and db_user and db_name:
        encoded_user = quote_plus(db_user)
        encoded_password = quote_plus(db_password)
        if postgres_scheme:
            return (
                f"postgresql+psycopg://{encoded_user}:{encoded_password}"
                f"@{db_host}:{db_port}/{db_name}"
            )
        return (
            f"mysql+pymysql://{encoded_user}:{encoded_password}"
            f"@{db_host}:{db_port}/{db_name}"
        )

    if allow_sqlite_fallback:
        return f"sqlite:///{DEFAULT_SQLITE_PATH}"
    return ""


def build_database_connect_args():
    ssl_ca = (
        os.environ.get("DB_SSL_CA")
        or os.environ.get("DATABASE_SSL_CA")
        or ""
    ).strip()
    verify_cert = env_flag("DB_SSL_VERIFY_CERT", default=bool(ssl_ca))
    verify_identity = env_flag("DB_SSL_VERIFY_IDENTITY", default=bool(ssl_ca))

    connect_args = {}
    if ssl_ca:
        connect_args["ssl_ca"] = ssl_ca
    if verify_cert:
        connect_args["ssl_verify_cert"] = True
    if verify_identity:
        connect_args["ssl_verify_identity"] = True
    return connect_args


def build_engine_options(database_uri):
    database_uri = normalize_database_uri(database_uri)
    if database_uri.startswith("sqlite"):
        return {
            "pool_pre_ping": True,
            "connect_args": {"check_same_thread": False},
        }

    options = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE_SECONDS", 280)),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", 20)),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 40)),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", 30)),
    }
    connect_args = build_database_connect_args()
    if connect_args:
        options["connect_args"] = connect_args
    return options


def ensure_instance_dirs():
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    (INSTANCE_DIR / "offline").mkdir(parents=True, exist_ok=True)


def forbid_sqlite_in_production(database_uri, env_name):
    if (env_name or "").strip().lower() == "production" and "sqlite" in (
        database_uri or ""
    ).lower():
        raise RuntimeError("SQLite forbidden in production")


def require_env_vars(names):
    missing = [name for name in names if not (os.environ.get(name) or "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(sorted(missing))
        )


def database_configured():
    if (os.environ.get("DATABASE_URL") or "").strip():
        return True
    db_host = (os.environ.get("DB_HOST") or "").strip()
    db_user = (os.environ.get("DB_USER") or "").strip()
    db_name = (os.environ.get("DB_NAME") or "").strip()
    return bool(db_host and db_user and db_name)


def require_database_config():
    if not database_configured():
        raise RuntimeError(
            "Database not configured: set DATABASE_URL or DB_HOST, DB_USER, DB_PASSWORD, and DB_NAME"
        )


WEAK_SECRET_KEYS = {
    "change-this-to-a-long-random-secret-key",
    "admin-secret-change-me",
    "delivery-secret-change-me",
    "customer-secret-change-me",
    "your_secure_secret_key",
    "dev",
    "secret",
}


def reject_weak_secret_key(secret_key, env_name):
    if (env_name or "").strip().lower() != "production":
        return
    normalized = (secret_key or "").strip().lower()
    if not normalized or len(normalized) < 32 or normalized in WEAK_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY must be a strong random value (32+ chars) in production"
        )
