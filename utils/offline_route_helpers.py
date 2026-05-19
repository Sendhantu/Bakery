"""Helpers for proactive offline queueing in admin/delivery routes."""

from sqlalchemy.exc import SQLAlchemyError


def queue_if_offline(offline_sync, queue_callable, *, success_message, redirect):
    if offline_sync.enabled and not offline_sync.is_online():
        request_id = queue_callable()
        from flask import flash

        flash(
            f"{success_message} (queued locally: {request_id[:8]}).",
            "warning",
        )
        return redirect
    return None


def handle_db_error_with_queue(exc, offline_sync, queue_callable, *, success_message, redirect):
    if isinstance(exc, SQLAlchemyError):
        from flask import flash
        from models import db

        db.session.rollback()
        request_id = queue_callable()
        flash(
            f"{success_message} (queued locally: {request_id[:8]}).",
            "warning",
        )
        return redirect
    raise exc
