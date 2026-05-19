from datetime import datetime

from flask import current_app

from models import BackupVerification, QueueMetric, cache, celery, db


@celery.task
def retry_offline_sync_actions():
    service = current_app.extensions["service_container"].offline_sync_service
    return service.flush_pending_actions()


@celery.task
def build_inventory_forecasts():
    forecasts = current_app.extensions["service_container"].forecast_service.build_daily_forecasts()
    return len(forecasts)


@celery.task
def generate_subscription_orders():
    orders = current_app.extensions["service_container"].subscription_service.create_due_orders()
    return len(orders)


@celery.task
def capture_queue_metrics():
    service = current_app.extensions["service_container"].offline_sync_service
    pending = service.pending_actions(limit=500) if service.enabled else []
    metric = QueueMetric(
        queue_name="offline_sync",
        backlog=len(pending),
        failed_count=0,
        retry_count=len([item for item in pending if item.get("status") == "retry"]),
    )
    db.session.add(metric)
    db.session.commit()
    return metric.id


@celery.task
def verify_backup_health():
    storage_result = current_app.extensions["service_container"].storage_service.verify_connection()
    db_result = "ok"
    try:
        db.session.execute(db.select(1))
    except Exception:
        db_result = "error"
        db.session.rollback()

    entries = [
        BackupVerification(provider="tidb", status=db_result, details=f"checked_at={datetime.utcnow().isoformat()}"),
        BackupVerification(provider="cloudinary", status=storage_result.get("status", "unknown"), details=storage_result.get("error", "")),
    ]
    db.session.add_all(entries)
    db.session.commit()
    return {"db": db_result, "storage": storage_result.get("status", "unknown")}


@celery.task
def aggregate_analytics_snapshot():
    from models import Order
    from realtime.events import emit_analytics_updated

    total_orders = Order.query.count()
    total_revenue = sum(float(order.total or 0) for order in Order.query.all())
    summary = {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "generated_at": datetime.utcnow().isoformat(),
    }
    cache.set("analytics:summary", summary, timeout=3600)
    emit_analytics_updated(summary)
    return total_orders


@celery.task
def generate_invoice_pdf(order_id):
    return current_app.extensions["service_container"].invoice_service.generate_and_store(order_id)


@celery.task
def process_birthday_rewards():
    return len(
        current_app.extensions["service_container"].loyalty_service.process_birthday_rewards()
    )


@celery.task
def send_abandoned_cart_reminders():
    from datetime import timedelta

    from models import Cart, User
    from tasks.messaging import send_whatsapp_message

    cutoff = datetime.utcnow() - timedelta(hours=2)
    stale_carts = Cart.query.filter(Cart.added_at <= cutoff).limit(50).all()
    sent = 0
    for cart in stale_carts:
        user = db.session.get(User, cart.user_id)
        if not user or not user.phone:
            continue
        if not current_app.config.get("WHATSAPP_ENABLED"):
            continue
        send_whatsapp_message.delay(
            user.phone,
            "You left items in your SweetCrumbs cart. Complete checkout before they sell out!",
        )
        sent += 1
    return sent
