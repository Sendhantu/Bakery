def init_sentry(app):
    dsn = (app.config.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:  # pragma: no cover
        app.logger.warning("Sentry DSN provided but sentry-sdk is not installed.")
        return

    traces = app.config.get("SENTRY_TRACES_SAMPLE_RATE")
    try:
        traces = float(traces) if traces is not None else 0.05
    except Exception:
        traces = 0.05

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FlaskIntegration(),
            CeleryIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=traces,
        environment=app.config.get("ENV", "development"),
        release=app.config.get("SENTRY_RELEASE"),
        send_default_pii=bool(app.config.get("SENTRY_SEND_PII", False)),
    )
