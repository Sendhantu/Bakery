from tasks.messaging import render_low_stock_digest, send_email, send_sms


def notify(user_id, title, message, ntype="order", link=""):
    from models import Notification, db

    db.session.add(
        Notification(
            user_id=user_id, title=title, message=message, type=ntype, link=link
        )
    )


def send_order_placed_email(order):
    user = order.customer
    items_html = "".join(
        f"<tr><td>{i.product_name}</td><td>{i.variant_name}</td>"
        f"<td>×{i.quantity}</td><td>₹{int(i.subtotal)}</td></tr>"
        for i in order.items.all()
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#6B3F1A">🎂 Order Confirmed — #{order.order_number}</h2>
      <p>Hi {user.name}, your order has been placed!</p>
      <table border="0" cellpadding="6" cellspacing="0" width="100%"
             style="border-collapse:collapse;border:1px solid #eee">
        <thead><tr style="background:#f5ede0">
          <th align="left">Product</th><th>Size</th><th>Qty</th><th>Amount</th>
        </tr></thead>
        <tbody>{items_html}</tbody>
        <tfoot><tr style="background:#f5ede0;font-weight:bold">
          <td colspan="3">Total</td><td>₹{int(order.total)}</td>
        </tr></tfoot>
      </table>
      <p style="color:#888;font-size:0.85rem;margin-top:1rem">
        Delivery on <strong>{order.delivery_date}</strong> · Slot: {order.delivery_slot}
      </p>
      <p>Thank you for choosing SweetCrumbs! 🍰</p>
    </div>
    """
    send_email.delay(user.email, f"Order Confirmed #{order.order_number}", html)


def send_status_update_email(order, new_status):
    user = order.customer
    status_msgs = {
        "PREPARING": "👩‍🍳 Your order is being prepared!",
        "PACKED": "📦 Your order has been packed and is ready for pickup.",
        "OUT_FOR_DELIVERY": "🛵 Your order is on its way!",
        "DELIVERED": "✅ Your order has been delivered. Enjoy!",
        "CANCELLED": "❌ Your order has been cancelled.",
        "ON_HOLD": "⏸️ Your order is on hold. Please check for further instructions.",
    }
    blurb = status_msgs.get(new_status, f"Your order status is now: {new_status}")
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#6B3F1A">Order Update — #{order.order_number}</h2>
      <p>Hi {user.name},</p>
      <p style="font-size:1.1rem">{blurb}</p>
      <p style="color:#888;font-size:0.85rem">Order total: ₹{int(order.total)}</p>
      <p>SweetCrumbs Bakery 🎂</p>
    </div>
    """
    send_email.delay(
        user.email,
        f'Order #{order.order_number} — {new_status.replace("_", " ").title()}',
        html,
    )


def send_low_stock_alert_email(admin_email, alerts):
    send_email.delay(
        admin_email,
        f"⚠️ Inventory Alert — {len(alerts)} item(s) need restocking",
        render_low_stock_digest(alerts),
    )


def send_order_sms(order, new_status=None):
    user = order.customer
    if not user.phone:
        return False
    if new_status:
        msg = (
            f'SweetCrumbs: Order #{order.order_number} is now '
            f'{new_status.replace("_", " ")}.'
        )
    else:
        msg = (
            f"SweetCrumbs: Your order #{order.order_number} "
            f"(₹{int(order.total)}) has been placed!"
        )
    return send_sms.delay(user.phone, msg)


def notify_order_status_change(order, new_status, old_status=None):
    from flask import current_app, url_for
    from models import LoyaltyLedger, db

    title = f"Order Update: {new_status}"
    message = f'Your order #{order.order_number} is now {new_status.replace("_", " ")}.'
    notify(
        order.user_id,
        title,
        message,
        "order",
        url_for("customer.order_detail", order_id=order.id),
    )

    if new_status == "DELIVERED" and (old_status or "").strip().upper() != "DELIVERED":
        existing_reward = LoyaltyLedger.query.filter_by(
            user_id=order.user_id,
            order_id=order.id,
            reason="order_earned",
        ).first()
        if existing_reward is None:
            pts = LoyaltyLedger.earn(order.user_id, order.id, order.total)
            if pts:
                notify(
                    order.user_id,
                    "🎉 Loyalty Points Earned!",
                    f"You earned {pts} points for order #{order.order_number}.",
                    "loyalty",
                    url_for("customer.loyalty"),
                )

    db.session.commit()

    try:
        send_status_update_email(order, new_status)
    except Exception:
        current_app.logger.exception(
            "Failed to send status update email for order %s", order.id
        )

    try:
        send_order_sms(order, new_status)
    except Exception:
        current_app.logger.exception(
            "Failed to send status update SMS for order %s", order.id
        )


def check_and_send_inventory_alerts():
    from flask import current_app
    from models import RawMaterial, User

    if not current_app.config.get("MAIL_ENABLED"):
        return

    alerts = []
    for material in RawMaterial.query.filter_by(is_active=True).all():
        if material.stock_status in ("low_stock", "out_of_stock"):
            alerts.append(
                {
                    "name": material.name,
                    "stock": float(material.stock),
                    "unit": material.unit,
                    "status": material.stock_status,
                }
            )

    if not alerts:
        return

    admins = User.query.filter_by(role="admin", is_active=True).all()
    for admin in admins:
        if admin.email:
            send_low_stock_alert_email(admin.email, alerts)
