import json
import os
from datetime import datetime
from decimal import Decimal

from flask import Flask, request, send_from_directory, url_for, jsonify, current_app, redirect, render_template
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf import CSRFProtect
from flask_socketio import join_room
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from api.v1 import api_v1_bp
from api.v2 import api_v2_bp
from bootstrap import build_service_container
from config import config
from infrastructure import (
    configure_logging,
    init_sentry,
    register_error_handlers,
    register_request_hooks,
    register_sqlalchemy_observers,
)
from models import User, bcrypt, cache, celery, db, limiter, socketio
from utils import (
    address_query,
    apply_security_headers,
    map_embed_url,
    map_link_url,
    should_force_https,
)

try:
    from flask_jwt_extended import JWTManager
except ImportError:  # pragma: no cover
    class JWTManager:  # type: ignore
        def init_app(self, *args, **kwargs):
            return None

try:
    from flask_migrate import Migrate
except ImportError:  # pragma: no cover
    class Migrate:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, *args, **kwargs):
            return None

login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
migrate = Migrate()
jwt = JWTManager()
CREDENTIAL_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "output", "dev_credentials.json"
)
STARTUP_BANNER_CACHE = set()

PORTAL_PORTS = {
    "customer": 5000,
    "admin": 5001,
    "delivery": 5002,
}

LOCAL_PORTAL_URLS = {
    role: f"http://127.0.0.1:{port}" for role, port in PORTAL_PORTS.items()
}

DEMO_PORTAL_CREDENTIALS = {
    "customer": {
        "email": "customer@test.com",
        "password": "customer123",
        "label": "Customer Demo",
    },
    "admin": {
        "email": "admin@bakery.com",
        "password": "Admin@bakery",
        "label": "Admin Default",
    },
    "delivery": {
        "email": "delivery@bakery.com",
        "password": "delivery123",
        "label": "Delivery Default",
    },
}


@socketio.on("connect")
def handle_socket_connect():
    portal = (request.args.get("portal") or "customer").strip().lower()
    if portal in {"customer", "admin", "delivery"}:
        join_room(portal)
    if portal == "admin":
        join_room("kds")
    join_room("global")


def env_flag(name):
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_portal_role(portal_role=None):
    candidate = (portal_role or os.environ.get("PORTAL_ROLE") or "").strip().lower()
    if candidate in PORTAL_PORTS:
        return candidate
    return "customer"


def configured_portal_url(role, config_name):
    env_key = f"{role.upper()}_PORTAL_URL"
    configured = (os.environ.get(env_key) or "").strip().rstrip("/")
    if configured:
        return configured
    if config_name != "production":
        return LOCAL_PORTAL_URLS[role]
    return ""


def _normalize_credential_entry(role, entry, default_source="default"):
    return {
        "role": role,
        "email": entry.get("email", ""),
        "password": entry.get("password", ""),
        "label": entry.get("label") or f"{role.title()} Account",
        "source": entry.get("source", default_source),
        "updated_at": entry.get("updated_at", ""),
    }


def _ensure_credential_registry_dir():
    os.makedirs(os.path.dirname(CREDENTIAL_REGISTRY_PATH), exist_ok=True)


def load_recorded_development_credentials():
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {}

    _ensure_credential_registry_dir()
    if not os.path.exists(CREDENTIAL_REGISTRY_PATH):
        return {}

    try:
        with open(CREDENTIAL_REGISTRY_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def save_recorded_development_credentials(payload):
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    _ensure_credential_registry_dir()
    with open(CREDENTIAL_REGISTRY_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def record_development_credential(role, email, password, label="", source="manual"):
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        or current_app.testing
        or not current_app.config.get("SHOW_DEMO_ACCOUNTS", False)
    ):
        return

    email = (email or "").strip().lower()
    password = (password or "").strip()
    role = (role or "customer").strip().lower()
    if not email or not password or role not in PORTAL_PORTS:
        return

    registry = load_recorded_development_credentials()
    registry[email] = {
        "role": role,
        "email": email,
        "password": password,
        "label": label or f"{role.title()} Account",
        "source": source,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    save_recorded_development_credentials(registry)


def get_available_development_credentials():
    credentials = {
        entry["email"]: _normalize_credential_entry(role, entry)
        for role, entry in DEMO_PORTAL_CREDENTIALS.items()
    }

    for email, entry in load_recorded_development_credentials().items():
        role = (entry.get("role") or "customer").strip().lower()
        if role not in PORTAL_PORTS:
            role = "customer"
        credentials[email] = _normalize_credential_entry(
            role, entry, default_source="recorded"
        )

    return sorted(
        credentials.values(),
        key=lambda item: (
            (
                ["customer", "admin", "delivery"].index(item["role"])
                if item["role"] in {"customer", "admin", "delivery"}
                else 99
            ),
            item["email"],
        ),
    )


def print_development_startup_banner(app):
    if (
        app.testing
        or app.config.get("ENV") == "production"
        or not app.config.get("SHOW_DEMO_ACCOUNTS", False)
        or os.environ.get("PORTAL_LAUNCHER_CHILD") == "1"
    ):
        return

    cache_key = (
        app.config.get("PORTAL_ROLE", "customer"),
        app.config.get("CUSTOMER_PORTAL_URL"),
        app.config.get("ADMIN_PORTAL_URL"),
        app.config.get("DELIVERY_PORTAL_URL"),
    )
    if cache_key in STARTUP_BANNER_CACHE:
        return

    STARTUP_BANNER_CACHE.add(cache_key)
    app.logger.info("SweetCrumbs local portals:")
    app.logger.info("  Customer: %s", app.config.get("CUSTOMER_PORTAL_URL"))
    app.logger.info("  Admin:    %s", app.config.get("ADMIN_PORTAL_URL"))
    app.logger.info("  Delivery: %s", app.config.get("DELIVERY_PORTAL_URL"))
    app.logger.info("Available login credentials:")
    for entry in get_available_development_credentials():
        app.logger.info(
            "  [%s] %s / %s%s",
            entry["role"].upper().ljust(8),
            entry["email"],
            entry["password"],
            f"  ({entry['label']})" if entry["label"] else "",
        )
    app.logger.info(
        "New customer signups and delivery password resets are also recorded here during development.",
    )


def configure_app(app, config_name="default", portal_role=None):
    config_name = (config_name or "default").strip().lower() or "default"
    if config_name not in config:
        config_name = "default"

    app.config.from_object(config[config_name])
    if hasattr(config[config_name], "init_app"):
        config[config_name].init_app(app)
    app.config["PORTAL_ROLE"] = resolve_portal_role(portal_role)
    current_role = app.config["PORTAL_ROLE"]
    app.config["SESSION_COOKIE_NAME"] = f"sweetcrumbs_{current_role}_session"
    app.config["OFFLINE_SYNC_DB_PATH"] = app.config.get(
        "OFFLINE_SYNC_DB_TEMPLATE", ""
    ).format(portal_role=current_role)
    show_demo_override = env_flag("SHOW_DEMO_ACCOUNTS")
    if show_demo_override is not None:
        app.config["SHOW_DEMO_ACCOUNTS"] = show_demo_override

    auto_init_override = env_flag("AUTO_INIT_DB")
    if auto_init_override is not None:
        app.config["AUTO_INIT_DB"] = auto_init_override

    for role in PORTAL_PORTS:
        app.config[f"{role.upper()}_PORTAL_URL"] = configured_portal_url(
            role, config_name
        )

    app.config.setdefault("JSON_SORT_KEYS", False)
    return config_name


def setup_middleware(app):
    if app.config.get("USE_PROXY_FIX"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


def build_socketio_origins(app):
    configured_origins = app.config.get("SOCKETIO_CORS_ALLOWED_ORIGINS")
    if configured_origins and configured_origins != "*":
        if isinstance(configured_origins, str):
            return [item.strip() for item in configured_origins.split(",") if item.strip()]
        return configured_origins
    if app.config.get("ENV") == "production":
        origins = [
            app.config.get("CUSTOMER_PORTAL_URL"),
            app.config.get("ADMIN_PORTAL_URL"),
            app.config.get("DELIVERY_PORTAL_URL"),
        ]
        return [origin for origin in origins if origin]
    return "*"


def setup_celery(app):
    broker = app.config.get("CELERY_BROKER_URL")
    backend = app.config.get("CELERY_RESULT_BACKEND")
    if not broker or not backend:
        return celery

    celery.conf.update(
        broker_url=broker,
        result_backend=backend,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        beat_schedule=app.config.get("CELERY_BEAT_SCHEDULE") or {},
        imports=("tasks",),
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    app.extensions["celery"] = celery
    return celery


def setup_extensions(app):
    db.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)
    cache.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    jwt.init_app(app)
    message_queue = app.config.get("REDIS_URL") or app.config.get("SOCKETIO_MESSAGE_QUEUE")
    socketio.init_app(
        app,
        async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "threading"),
        cors_allowed_origins=build_socketio_origins(app),
        message_queue=message_queue,
    )
    setup_celery(app)
    import tasks  # noqa: F401 — register Celery task modules

    migrate.init_app(app, db, compare_type=True)
    login_manager.init_app(app)
    login_manager.session_protection = app.config.get(
        "LOGIN_SESSION_PROTECTION", "basic"
    )
    login_manager.login_view = "auth.login"
    if app.config.get("PORTAL_ROLE") == "admin":
        login_manager.login_view = "admin.admin_login"
    elif app.config.get("PORTAL_ROLE") == "delivery":
        login_manager.login_view = "delivery.delivery_login"
    login_manager.login_message_category = "info"

    @app.before_request
    def enforce_https_in_production():
        if should_force_https(app, request):
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))


def setup_security(app):
    @app.after_request
    def attach_security_headers(response):
        return apply_security_headers(response, app)


def register_blueprints(app):
    from routes.auth import auth_bp, oauth
    from routes.customer import customer_bp
    from routes.admin import admin_bp
    from routes.delivery import delivery_bp
    from routes.api import api_bp

    oauth.init_app(app)

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(customer_bp, url_prefix="")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(delivery_bp, url_prefix="/delivery")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")
    if app.config.get("FEATURE_FLAGS", {}).get("api.v2.enabled", False):
        app.register_blueprint(api_v2_bp, url_prefix="/api/v2")


def register_core_routes(app):
    @app.route("/robots.txt")
    def robots_txt():
        return send_from_directory(
            app.static_folder, "robots.txt", mimetype="text/plain"
        )

    @app.route("/admin/manifest.json")
    def admin_manifest():
        return jsonify(
            {
                "name": "SweetCrumbs Admin Portal",
                "short_name": "Sweet Admin",
                "start_url": "/admin/",
                "display": "standalone",
                "background_color": "#FDF6EC",
                "theme_color": "#5C3D2E",
                "icons": [
                    {
                        "src": url_for("static", filename="icons/bakery-app.svg"),
                        "sizes": "512x512",
                        "type": "image/svg+xml",
                    }
                ],
            }
        )

    @app.route("/delivery/manifest.json")
    def delivery_manifest():
        return jsonify(
            {
                "name": "SweetCrumbs Delivery Portal",
                "short_name": "Sweet Delivery",
                "start_url": "/delivery/",
                "display": "standalone",
                "background_color": "#FDF6EC",
                "theme_color": "#5C3D2E",
                "icons": [
                    {
                        "src": url_for("static", filename="icons/bakery-app.svg"),
                        "sizes": "512x512",
                        "type": "image/svg+xml",
                    }
                ],
            }
        )

    @app.route("/admin/offline")
    def admin_offline():
        return render_template("admin/offline.html")

    @app.route("/delivery/offline")
    def delivery_offline():
        return render_template("delivery/offline.html")

    @app.route("/admin/service-worker.js")
    def admin_service_worker():
        script = _build_service_worker_script(
            cache_name="sweetcrumbs-admin-v1",
            offline_url=url_for("admin_offline"),
            warm_urls=[
                url_for("admin.dashboard"),
                url_for("admin_offline"),
                url_for("static", filename="css/main.css"),
                url_for("static", filename="js/main.js"),
            ],
        )
        return app.response_class(script, mimetype="application/javascript")

    @app.route("/delivery/service-worker.js")
    def delivery_service_worker():
        script = _build_service_worker_script(
            cache_name="sweetcrumbs-delivery-v1",
            offline_url=url_for("delivery_offline"),
            warm_urls=[
                url_for("delivery.dashboard"),
                url_for("delivery_offline"),
                url_for("static", filename="css/main.css"),
                url_for("static", filename="js/main.js"),
            ],
        )
        return app.response_class(script, mimetype="application/javascript")

    @app.route("/healthz")
    def healthz():
        database_state = "ok"
        redis_state = "ok"
        celery_state = "ok"
        storage_state = "ok"
        status_code = 200
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            database_state = "unhealthy"
            status_code = 503
        try:
            redis_url = app.config.get("REDIS_URL")
            if redis_url:
                from redis import Redis

                Redis.from_url(redis_url).ping()
            elif app.config.get("ENV") == "production":
                raise RuntimeError("REDIS_URL missing")
        except Exception:
            redis_state = "unhealthy"
            status_code = 503
        try:
            broker = app.config.get("CELERY_BROKER_URL")
            backend = app.config.get("CELERY_RESULT_BACKEND")
            if not broker or not backend:
                if app.config.get("ENV") == "production":
                    raise RuntimeError("Celery broker/backend not configured")
            else:
                from redis import Redis

                Redis.from_url(broker).ping()
                registered = list(celery.tasks.keys())
                if not any(name.startswith("tasks.") for name in registered):
                    celery_state = "degraded"
        except Exception:
            celery_state = "unhealthy"
            status_code = 503

        storage_check = app.extensions["service_container"].storage_service.verify_connection()
        storage_state = storage_check["status"]
        if app.config.get("ENV") == "production" and storage_state != "ok":
            status_code = 503

        return (
            jsonify(
                status="ok" if status_code == 200 else "error",
                database=database_state,
                redis=redis_state,
                celery=celery_state,
                storage=storage_state,
            ),
            status_code,
        )


def register_context_processors(app):
    @app.context_processor
    def inject_globals():
        from models import Category, Notification, get_loyalty_config
        from flask_login import current_user
        from sqlalchemy.exc import SQLAlchemyError

        current_portal_role = app.config.get("PORTAL_ROLE", "customer")

        def build_parallel_login_url():
            host, _, port = request.host.partition(":")
            if host not in {"127.0.0.1", "localhost"}:
                return None, None

            alternate_host = "localhost" if host == "127.0.0.1" else "127.0.0.1"
            port_suffix = f":{port}" if port else ""
            return (
                f'{request.scheme}://{alternate_host}{port_suffix}{url_for("auth.login")}',
                alternate_host,
            )

        def build_portal_urls():
            request_host = request.host.split(":", 1)[0].lower()
            if request_host in {"127.0.0.1", "localhost"}:
                return {
                    role: f"{request.scheme}://{request_host}:{port}"
                    for role, port in PORTAL_PORTS.items()
                }

            current_root = f"{request.scheme}://{request.host}"
            portal_urls = {}
            for role in PORTAL_PORTS:
                configured = (
                    app.config.get(f"{role.upper()}_PORTAL_URL") or ""
                ).rstrip("/")
                portal_urls[role] = configured or current_root
            return portal_urls

        categories = []
        unread_count = 0
        try:
            categories = Category.query.all()
            if current_user.is_authenticated:
                unread_count = Notification.query.filter_by(
                    user_id=current_user.id, is_read=False
                ).count()
        except SQLAlchemyError:
            db.session.rollback()
        parallel_login_url, parallel_host = build_parallel_login_url()
        return dict(
            categories=categories,
            unread_notifs=unread_count,
            bakery_name=app.config["BAKERY_NAME"],
            site_meta_description=app.config.get("SITE_META_DESCRIPTION", ""),
            store_details=app.config["STORE_DETAILS"],
            current_portal_role=current_portal_role,
            parallel_login_url=parallel_login_url,
            parallel_host=parallel_host,
            current_year=datetime.now().year,
            portal_urls=build_portal_urls(),
            portal_demo_credentials={
                entry["role"]: entry for entry in get_available_development_credentials()
            },
            show_demo_accounts=app.config.get("SHOW_DEMO_ACCOUNTS", False),
            feature_flags=app.config.get("FEATURE_FLAGS", {}),
            loyalty_config=get_loyalty_config(),
            auth_admin_2fa_provision={
                "enabled": app.config.get("AUTH_ADMIN_2FA_PROVISION_ENABLED", False),
                "providers": app.config.get("AUTH_ADMIN_2FA_PROVIDERS", []),
                "enforcement": app.config.get("AUTH_ADMIN_2FA_ENFORCEMENT", "off"),
            },
            address_query=address_query,
            map_link_url=map_link_url,
            map_embed_url=map_embed_url,
        )
def initialize_database(app, seed=False):
    with app.app_context():
        from flask_migrate import upgrade

        upgrade()
        if seed:
            seed_data(app)


def _build_service_worker_script(cache_name, offline_url, warm_urls):
    precache = json.dumps(list(dict.fromkeys(warm_urls)))
    return f"""
const CACHE_NAME = "{cache_name}";
const OFFLINE_URL = "{offline_url}";
const PRECACHE_URLS = {precache};

self.addEventListener("install", (event) => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting())
  );
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil(self.clients.claim());
}});

self.addEventListener("fetch", (event) => {{
  if (event.request.method !== "GET") {{
    return;
  }}
  event.respondWith(
    fetch(event.request)
      .then((response) => {{
        const cloned = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
        return response;
      }})
      .catch(() =>
        caches.match(event.request).then((cached) => cached || caches.match(OFFLINE_URL))
      )
  );
}});

self.addEventListener("push", (event) => {{
  const payload = event.data ? event.data.json() : {{}};
  const title = payload.title || "SweetCrumbs";
  const options = {{
    body: payload.body || "New bakery update available.",
    icon: "/static/icons/bakery-app.svg",
    data: payload.data || {{}},
  }};
  event.waitUntil(self.registration.showNotification(title, options));
}});

self.addEventListener("notificationclick", (event) => {{
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/";
  event.waitUntil(clients.openWindow(targetUrl));
}});
"""


def start_local_sync_worker(app):
    if (
        app.testing
        or not app.config.get("ENABLE_LOCAL_SYNC_WORKER", False)
        or app.config.get("PORTAL_ROLE") not in {"admin", "delivery"}
        or app.config.get("ENV") == "production"
    ):
        return

    if app.extensions.get("offline_sync_worker_started"):
        return

    app.extensions["offline_sync_worker_started"] = True
    sync_service = app.extensions["service_container"].offline_sync_service

    def _runner():
        with app.app_context():
            while True:
                try:
                    result = sync_service.flush_pending_actions()
                    if any(result.values()):
                        app.logger.info("offline_sync_flush %s", result)
                except Exception:
                    app.logger.exception("offline_sync_flush_failed")
                socketio.sleep(app.config.get("SYNC_RETRY_INTERVAL_SECONDS", 30))

    socketio.start_background_task(_runner)


def create_app(config_name="default", portal_role=None):
    app = Flask(__name__)
    configure_app(app, config_name, portal_role)
    configure_logging(app)
    setup_middleware(app)
    setup_extensions(app)
    init_sentry(app)
    setup_security(app)
    build_service_container(app)
    register_request_hooks(app)
    register_error_handlers(app)
    register_blueprints(app)
    register_core_routes(app)
    register_context_processors(app)
    with app.app_context():
        register_sqlalchemy_observers(app)
    if app.config.get("AUTO_INIT_DB"):
        initialize_database(app, seed=app.config.get("SHOW_DEMO_ACCOUNTS", False))
    start_local_sync_worker(app)
    print_development_startup_banner(app)

    return app


def seed_data(app):
    """Seed demo data"""
    with app.app_context():
        from models import (
            User,
            Category,
            Product,
            ProductVariant,
            Coupon,
            DeliveryAgent,
            RawMaterial,
            ProductMaterial,
        )

        # Admin user
        admin = User.query.filter_by(
            email=DEMO_PORTAL_CREDENTIALS["admin"]["email"]
        ).first()
        if not admin:
            admin = User(
                name="Baker Admin",
                email=DEMO_PORTAL_CREDENTIALS["admin"]["email"],
                role="admin",
                phone="9999999999",
            )
            db.session.add(admin)
        admin.name = "Baker Admin"
        admin.role = "admin"
        admin.phone = "9999999999"
        admin.is_active = True
        admin.set_password(DEMO_PORTAL_CREDENTIALS["admin"]["password"])
        record_development_credential(
            "admin",
            DEMO_PORTAL_CREDENTIALS["admin"]["email"],
            DEMO_PORTAL_CREDENTIALS["admin"]["password"],
            label=DEMO_PORTAL_CREDENTIALS["admin"]["label"],
            source="seeded",
        )

        # Delivery user
        duser = User.query.filter_by(
            email=DEMO_PORTAL_CREDENTIALS["delivery"]["email"]
        ).first()
        if not duser:
            duser = User(
                name="Delivery Staff",
                email=DEMO_PORTAL_CREDENTIALS["delivery"]["email"],
                role="delivery",
                phone="8888888888",
            )
            db.session.add(duser)
            db.session.flush()
        duser.name = "Delivery Staff"
        duser.role = "delivery"
        duser.phone = "8888888888"
        duser.is_active = True
        duser.set_password(DEMO_PORTAL_CREDENTIALS["delivery"]["password"])
        agent = DeliveryAgent.query.filter_by(user_id=duser.id).first()
        if not agent:
            agent = DeliveryAgent(
                user_id=duser.id, name="Delivery Staff", phone="8888888888"
            )
            db.session.add(agent)
        agent.name = "Delivery Staff"
        agent.phone = "8888888888"
        record_development_credential(
            "delivery",
            DEMO_PORTAL_CREDENTIALS["delivery"]["email"],
            DEMO_PORTAL_CREDENTIALS["delivery"]["password"],
            label=DEMO_PORTAL_CREDENTIALS["delivery"]["label"],
            source="seeded",
        )

        # Sample customer
        cust = User.query.filter_by(
            email=DEMO_PORTAL_CREDENTIALS["customer"]["email"]
        ).first()
        if not cust:
            cust = User(
                name="Test Customer",
                email=DEMO_PORTAL_CREDENTIALS["customer"]["email"],
                role="customer",
                phone="7777777777",
            )
            db.session.add(cust)
        cust.name = "Test Customer"
        cust.role = "customer"
        cust.phone = "7777777777"
        cust.is_active = True
        cust.set_password(DEMO_PORTAL_CREDENTIALS["customer"]["password"])
        record_development_credential(
            "customer",
            DEMO_PORTAL_CREDENTIALS["customer"]["email"],
            DEMO_PORTAL_CREDENTIALS["customer"]["password"],
            label=DEMO_PORTAL_CREDENTIALS["customer"]["label"],
            source="seeded",
        )

        # Categories
        cats_data = [
            ("Cakes", "🎂"),
            ("Pastries", "🥐"),
            ("Cookies", "🍪"),
            ("Breads", "🍞"),
            ("Cupcakes", "🧁"),
            ("Pies", "🥧"),
        ]
        categories = {}
        for cname, icon in cats_data:
            category = Category.query.filter_by(name=cname).first()
            if not category:
                category = Category(name=cname, icon=icon)
                db.session.add(category)
                db.session.flush()
            categories[cname] = category

        products_file = os.path.join(os.path.dirname(__file__), "data", "products.json")
        if os.path.exists(products_file):
            with open(products_file, "r", encoding="utf-8") as handle:
                products_data = json.load(handle)
        else:
            products_data = []

        placeholder_images = {None, "", "default-product.jpg"}
        for pd in products_data:
            category_name = pd.get("category") or "Cakes"
            category = categories.get(category_name)
            if category is None:
                category = Category(name=category_name, icon="🎂")
                db.session.add(category)
                db.session.flush()
                categories[category_name] = category

            existing_product = Product.query.filter_by(name=pd["name"]).first()
            if existing_product:
                if existing_product.image in placeholder_images and pd.get("image"):
                    existing_product.image = pd["image"]
                existing_product.category_id = category.id
                existing_product.description = pd.get("description", existing_product.description)
                existing_product.ingredients = pd.get("ingredients", existing_product.ingredients)
                existing_product.preparation = pd.get("preparation", existing_product.preparation)
                existing_product.base_price = Decimal(str(pd.get("base_price", existing_product.base_price)))
                existing_product.is_eggless = pd.get("is_eggless", existing_product.is_eggless)
                existing_product.is_featured = pd.get("is_featured", existing_product.is_featured)
                existing_product.occasion_tags = pd.get("occasion_tags", existing_product.occasion_tags)
                continue

            product_payload = {
                "name": pd.get("name"),
                "description": pd.get("description"),
                "ingredients": pd.get("ingredients"),
                "preparation": pd.get("preparation"),
                "base_price": Decimal(str(pd.get("base_price", 0))),
                "image": pd.get("image"),
                "category_id": category.id,
                "is_eggless": pd.get("is_eggless", False),
                "is_active": pd.get("is_active", True),
                "is_featured": pd.get("is_featured", False),
                "occasion_tags": pd.get("occasion_tags", ""),
            }
            prod = Product(**product_payload)
            db.session.add(prod)
            db.session.flush()
            for variant in pd.get("variants", []):
                db.session.add(
                    ProductVariant(
                        product_id=prod.id,
                        name=variant.get("name", "Default"),
                        price=Decimal(str(variant.get("price", 0))),
                        stock=int(variant.get("stock", 0)),
                    )
                )

        raw_materials_data = [
            ("All-Purpose Flour", "kg", 40, 8, 62),
            ("Butter", "kg", 18, 4, 540),
            ("Sugar", "kg", 30, 6, 48),
            ("Dark Chocolate", "kg", 16, 4, 760),
            ("Heavy Cream", "litre", 12, 3, 220),
            ("Cream Cheese", "kg", 9, 2, 410),
            ("Vanilla Extract", "litre", 4, 1, 980),
            ("Cherries", "kg", 10, 2, 260),
            ("Yeast", "kg", 5, 1, 180),
            ("Chocolate Chips", "kg", 8, 2, 420),
        ]
        for name, unit, stock, reorder_level, cost in raw_materials_data:
            if not RawMaterial.query.filter_by(name=name).first():
                db.session.add(
                    RawMaterial(
                        name=name,
                        unit=unit,
                        stock=stock,
                        reorder_level=reorder_level,
                        cost_per_unit=cost,
                    )
                )
        db.session.flush()

        recipe_map = {
            "Classic Chocolate Cake": {
                "All-Purpose Flour": Decimal("0.35"),
                "Butter": Decimal("0.18"),
                "Sugar": Decimal("0.22"),
                "Dark Chocolate": Decimal("0.20"),
                "Heavy Cream": Decimal("0.15"),
            },
            "Red Velvet Cake": {
                "All-Purpose Flour": Decimal("0.32"),
                "Butter": Decimal("0.16"),
                "Sugar": Decimal("0.20"),
                "Cream Cheese": Decimal("0.18"),
                "Vanilla Extract": Decimal("0.03"),
            },
            "Eggless Vanilla Sponge": {
                "All-Purpose Flour": Decimal("0.28"),
                "Sugar": Decimal("0.19"),
                "Butter": Decimal("0.12"),
                "Vanilla Extract": Decimal("0.02"),
                "Heavy Cream": Decimal("0.08"),
            },
            "Butter Croissant": {
                "All-Purpose Flour": Decimal("0.12"),
                "Butter": Decimal("0.08"),
                "Yeast": Decimal("0.01"),
                "Sugar": Decimal("0.02"),
            },
            "Choco Chip Cookies": {
                "All-Purpose Flour": Decimal("0.10"),
                "Butter": Decimal("0.06"),
                "Sugar": Decimal("0.05"),
                "Chocolate Chips": Decimal("0.07"),
            },
            "Black Forest Cake": {
                "All-Purpose Flour": Decimal("0.34"),
                "Butter": Decimal("0.16"),
                "Sugar": Decimal("0.20"),
                "Heavy Cream": Decimal("0.18"),
                "Cherries": Decimal("0.10"),
                "Dark Chocolate": Decimal("0.12"),
            },
        }

        for product_name, material_requirements in recipe_map.items():
            product = Product.query.filter_by(name=product_name).first()
            if not product:
                continue

            for material_name, quantity_required in material_requirements.items():
                material = RawMaterial.query.filter_by(name=material_name).first()
                if not material:
                    continue

                existing_requirement = ProductMaterial.query.filter_by(
                    product_id=product.id, raw_material_id=material.id
                ).first()
                if existing_requirement:
                    continue

                db.session.add(
                    ProductMaterial(
                        product_id=product.id,
                        raw_material_id=material.id,
                        quantity_required=quantity_required,
                    )
                )

        # Coupons
        if not Coupon.query.filter_by(code="WELCOME10").first():
            from datetime import datetime, timedelta

            db.session.add(
                Coupon(
                    code="WELCOME10",
                    discount_type="percentage",
                    discount_value=10,
                    min_order_value=300,
                    max_uses=500,
                    valid_until=datetime.utcnow() + timedelta(days=365),
                )
            )
        if not Coupon.query.filter_by(code="FLAT50").first():
            from datetime import datetime, timedelta

            db.session.add(
                Coupon(
                    code="FLAT50",
                    discount_type="flat",
                    discount_value=50,
                    min_order_value=500,
                    max_uses=200,
                    valid_until=datetime.utcnow() + timedelta(days=365),
                )
            )

        db.session.commit()
        print("✅ Seed data inserted successfully.")

# ─────────────────────────────────────────────────────────────────────────────
# Local development only — python app.py starts 3 portals on separate ports
# Production uses wsgi.py via gunicorn (Render)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import threading

    def run_customer():
        customer_app = create_app("development", portal_role="customer")
        with customer_app.app_context():
            db.create_all()
            seed_data(customer_app)
        customer_app.run(debug=False, use_reloader=False, port=5000)

    def run_admin():
        admin_app = create_app("development", portal_role="admin")
        admin_app.run(debug=False, use_reloader=False, port=5001)

    def run_delivery():
        delivery_app = create_app("development", portal_role="delivery")
        delivery_app.run(debug=False, use_reloader=False, port=5002)

    customer_thread = threading.Thread(target=run_customer)
    admin_thread = threading.Thread(target=run_admin)
    delivery_thread = threading.Thread(target=run_delivery)

    customer_thread.start()
    admin_thread.start()
    delivery_thread.start()

    customer_thread.join()
    admin_thread.join()
    delivery_thread.join()

#cd /Users/sendhanumapathy/Downloads/bakery/customer_app && python app.py
#cd /Users/sendhanumapathy/Downloads/bakery/admin_app && python app.py
#cd /Users/sendhanumapathy/Downloads/bakery/delivery_app && python app.py
