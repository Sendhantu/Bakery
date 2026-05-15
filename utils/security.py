from datetime import datetime, timedelta


def get_login_lockout_window(config):
    minutes = config.get("LOGIN_LOCKOUT_MINUTES", 15)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 15
    return timedelta(minutes=max(1, minutes))


def build_permissions_policy(allow_geolocation=False):
    geolocation_policy = "(self)" if allow_geolocation else "()"
    return f"geolocation={geolocation_policy}, microphone=(), camera=()"


def apply_security_headers(response, app):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        build_permissions_policy(
            allow_geolocation=app.config.get("ALLOW_GEOLOCATION", True)
        ),
    )
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if app.config.get("ENV") == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains; preload",
        )
    if app.config.get("CONTENT_SECURITY_POLICY"):
        response.headers.setdefault(
            "Content-Security-Policy",
            app.config["CONTENT_SECURITY_POLICY"],
        )
    return response


def should_force_https(app, request):
    return (
        app.config.get("ENV") == "production"
        and not request.is_secure
        and request.endpoint not in {"healthz"}
        and not request.path.startswith("/static/")
    )


def admin_2fa_provision(config):
    return {
        "enabled": bool(config.get("AUTH_ADMIN_2FA_PROVISION_ENABLED", False)),
        "providers": list(config.get("AUTH_ADMIN_2FA_PROVIDERS", [])),
        "enforcement_mode": config.get("AUTH_ADMIN_2FA_ENFORCEMENT", "off"),
    }


def suspicious_login_window(now=None, minutes=30):
    current_time = now or datetime.utcnow()
    return current_time - timedelta(minutes=max(1, int(minutes or 30)))
