import json
import logging
import time
from datetime import datetime

from flask import jsonify, request, g
from sqlalchemy import event

from exceptions import ValidationError
from models import db


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_logging(app):
    app.logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO if not app.debug else logging.DEBUG)
    app.logger.propagate = False


def register_request_hooks(app):
    @app.before_request
    def log_request_start():
        g.request_started_at = time.perf_counter()

    @app.after_request
    def log_request_end(response):
        started_at = getattr(g, "request_started_at", None)
        duration_ms = 0
        if started_at is not None:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
        app.logger.info(
            "request_complete",
            extra={
                "request_id": request.headers.get("X-Request-ID", ""),
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def register_sqlalchemy_observers(app):
    threshold_seconds = max(
        0.05,
        int(app.config.get("SLOW_QUERY_THRESHOLD_MS", 250)) / 1000,
    )

    @event.listens_for(db.engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start_time", []).append(time.perf_counter())

    @event.listens_for(db.engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started_stack = conn.info.get("query_start_time", [])
        if not started_stack:
            return
        total = time.perf_counter() - started_stack.pop(-1)
        if total >= threshold_seconds:
            app.logger.warning(
                "slow_query",
                extra={
                    "duration_ms": int(total * 1000),
                    "statement": statement[:600],
                },
            )


def register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def handle_validation_error(exc):
        app.logger.info("validation_error: %s", exc)
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"ok": False, "message": str(exc)}), 400
        return (
            jsonify({"ok": False, "message": str(exc)}),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(exc):
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"ok": False, "message": "Not found"}), 404
        return exc

    @app.errorhandler(Exception)
    def handle_exception(exc):
        app.logger.exception("unhandled_exception")
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"ok": False, "message": "Internal server error"}), 500
        raise exc
