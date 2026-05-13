"""
utils.py — Shared helpers for SweetCrumbs Bakery
Covers: email, SMS, in-app notifications, decimal parsing.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime


# ─────────────────────────────────────────
# DECIMAL PARSING
# ─────────────────────────────────────────
def parse_decimal(value, field_name='value', default='0') -> Decimal:
    raw = (value or '').strip()
    if not raw:
        return Decimal(default)
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f'Invalid {field_name}: "{raw}"')


# ─────────────────────────────────────────
# IN-APP NOTIFICATION
# ─────────────────────────────────────────
def notify(user_id, title, message, ntype='order', link=''):
    """Add an in-app notification. Caller must db.session.commit()."""
    from models import db, Notification
    db.session.add(Notification(
        user_id=user_id, title=title, message=message,
        type=ntype, link=link
    ))


def save_address_for_customer(user_id, payload, make_default=False):
    """Create or update a saved address without depending on a blueprint import."""
    from models import db, SavedAddress

    existing = SavedAddress.query.filter_by(
        user_id=user_id,
        address_line1=payload['address_line1'],
        address_line2=payload['address_line2'],
        city=payload['city'],
        pincode=payload['pincode'],
        phone=payload['phone'],
    ).first()

    if make_default or not SavedAddress.query.filter_by(user_id=user_id).first():
        SavedAddress.query.filter_by(user_id=user_id, is_default=True).update({'is_default': False})
        make_default = True

    if existing:
        existing.label = payload['label']
        existing.is_default = make_default or existing.is_default
        return existing

    address = SavedAddress(
        user_id=user_id,
        label=payload['label'],
        address_line1=payload['address_line1'],
        address_line2=payload['address_line2'],
        city=payload['city'],
        pincode=payload['pincode'],
        phone=payload['phone'],
        is_default=make_default,
    )
    db.session.add(address)
    return address


def get_saved_addresses_for_user(user_id):
    from models import SavedAddress

    return SavedAddress.query.filter_by(user_id=user_id).order_by(
        SavedAddress.is_default.desc(),
        SavedAddress.updated_at.desc(),
        SavedAddress.id.desc(),
    ).all()


def get_selected_saved_address(user_id, address_id):
    from models import SavedAddress

    if not address_id:
        return None
    return SavedAddress.query.filter_by(id=address_id, user_id=user_id).first()


def extract_address_payload(form, fallback_address=None, default_phone=''):
    form = form or {}
    payload = {
        'label': (form.get('address_label') or form.get('label') or '').strip() or 'Saved Address',
        'address_line1': (form.get('address_line1') or '').strip(),
        'address_line2': (form.get('address_line2') or '').strip(),
        'city': (form.get('city') or '').strip(),
        'pincode': (form.get('pincode') or '').strip(),
        'phone': (form.get('phone') or default_phone or '').strip(),
    }

    if fallback_address:
        payload['address_line1'] = payload['address_line1'] or (fallback_address.address_line1 or '')
        payload['address_line2'] = payload['address_line2'] or (fallback_address.address_line2 or '')
        payload['city'] = payload['city'] or (fallback_address.city or '')
        payload['pincode'] = payload['pincode'] or (fallback_address.pincode or '')
        payload['phone'] = payload['phone'] or (fallback_address.phone or '')
        payload['label'] = payload['label'] or fallback_address.label or 'Saved Address'

    return payload


def validate_address_payload(payload):
    errors = []
    required_fields = {
        'address_line1': 'Address line 1 is required.',
        'city': 'City is required.',
        'pincode': 'PIN code is required.',
        'phone': 'Phone number is required.',
    }
    for field, message in required_fields.items():
        if not (payload.get(field) or '').strip():
            errors.append(message)

    pincode = (payload.get('pincode') or '').strip()
    if pincode and (not pincode.isdigit() or len(pincode) != 6):
        errors.append('PIN code must be a valid 6-digit number.')

    phone = ''.join(ch for ch in (payload.get('phone') or '') if ch.isdigit())
    if phone and len(phone) < 10:
        errors.append('Phone number must be at least 10 digits.')

    return errors


# ─────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────
from models import celery

@celery.task
def send_email(to, subject, html_body, text_body=None):
    """
    Send an email via Flask-Mail asynchronously.
    Silently skips if MAIL_ENABLED is False.
    Logs success/failure to EmailLog table.
    """
    from flask import current_app
    from models import db, EmailLog

    if not current_app.config.get('MAIL_ENABLED'):
        return False

    log = EmailLog(to_email=to, subject=subject, body_key='custom')
    try:
        from flask_mail import Message as MailMsg

        mail = current_app.extensions.get('mail')
        if mail is None:
            log.status = 'failed'
            log.error = 'Flask-Mail extension is not initialized.'
            db.session.add(log)
            db.session.commit()
            current_app.logger.warning('Email skipped because Flask-Mail is not initialized.')
            return False

        msg = MailMsg(subject=subject, recipients=[to],
                      html=html_body, body=text_body or '')
        mail.send(msg)
        log.status = 'sent'
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as exc:
        log.status = 'failed'
        log.error  = str(exc)[:400]
        db.session.add(log)
        db.session.commit()
        current_app.logger.error(f'Email failed to {to}: {exc}')
        return False


def send_order_placed_email(order):
    """Email the customer when their order is placed."""
    user = order.customer
    items_html = ''.join(
        f'<tr><td>{i.product_name}</td><td>{i.variant_name}</td>'
        f'<td>×{i.quantity}</td><td>₹{int(i.subtotal)}</td></tr>'
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
    send_email.delay(user.email, f'Order Confirmed #{order.order_number}', html)


def send_status_update_email(order, new_status):
    """Email the customer when their order status changes."""
    user = order.customer
    status_msgs = {
        'PREPARING':        '👩‍🍳 Your order is being prepared!',
        'PACKED':           '📦 Your order has been packed and is ready for pickup.',
        'OUT_FOR_DELIVERY': '🛵 Your order is on its way!',
        'DELIVERED':        '✅ Your order has been delivered. Enjoy!',
        'CANCELLED':        '❌ Your order has been cancelled.',
        'ON_HOLD':          '⏸️ Your order is on hold. Please check for further instructions.',
    }
    blurb = status_msgs.get(new_status, f'Your order status is now: {new_status}')
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#6B3F1A">Order Update — #{order.order_number}</h2>
      <p>Hi {user.name},</p>
      <p style="font-size:1.1rem">{blurb}</p>
      <p style="color:#888;font-size:0.85rem">Order total: ₹{int(order.total)}</p>
      <p>SweetCrumbs Bakery 🎂</p>
    </div>
    """
    send_email.delay(user.email, f'Order #{order.order_number} — {new_status.replace("_", " ").title()}', html)


def send_low_stock_alert_email(admin_email, alerts):
    """
    Email the admin a low-stock / out-of-stock digest.
    alerts = list of dicts: {name, stock, unit, status}
    """
    rows = ''.join(
        f'<tr><td>{a["name"]}</td><td>{a["stock"]} {a["unit"]}</td>'
        f'<td style="color:{"red" if a["status"]=="out_of_stock" else "orange"}">'
        f'{"Out of Stock" if a["status"]=="out_of_stock" else "Low Stock"}</td></tr>'
        for a in alerts
    )
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto">
      <h2 style="color:#6B3F1A">🧂 Inventory Alert — SweetCrumbs</h2>
      <p>The following items need attention:</p>
      <table border="0" cellpadding="6" cellspacing="0" width="100%"
             style="border-collapse:collapse;border:1px solid #eee">
        <thead><tr style="background:#f5ede0">
          <th align="left">Material</th><th>Current Stock</th><th>Status</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:0.85rem;color:#888">Sent automatically by SweetCrumbs at {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC</p>
    </div>
    """
    send_email.delay(admin_email, f'⚠️ Inventory Alert — {len(alerts)} item(s) need restocking', html)


# ─────────────────────────────────────────
# SMS (Twilio stub)
# ─────────────────────────────────────────
@celery.task
def send_sms(to_number, message):
    """
    Send an SMS via Twilio asynchronously.
    Returns True on success, False if disabled or on error.
    Configure TWILIO_* env vars to enable.
    """
    from flask import current_app
    if not current_app.config.get('SMS_ENABLED'):
        return False
    try:
        from twilio.rest import Client
        client = Client(
            current_app.config['TWILIO_ACCOUNT_SID'],
            current_app.config['TWILIO_AUTH_TOKEN']
        )
        client.messages.create(
            body=message,
            from_=current_app.config['TWILIO_FROM_NUMBER'],
            to=to_number
        )
        return True
    except Exception as exc:
        current_app.logger.error(f'SMS failed to {to_number}: {exc}')
        return False


def send_order_sms(order, new_status=None):
    """Send an SMS to the customer on order placed or status update."""
    user = order.customer
    if not user.phone:
        return False
    if new_status:
        msg = f'SweetCrumbs: Order #{order.order_number} is now {new_status.replace("_", " ")}.'
    else:
        msg = f'SweetCrumbs: Your order #{order.order_number} (₹{int(order.total)}) has been placed!'
    return send_sms.delay(user.phone, msg)


def notify_order_status_change(order, new_status):
    from flask import current_app, url_for
    from models import db

    title = f'Order Update: {new_status}'
    message = f'Your order #{order.order_number} is now {new_status.replace("_", " ")}.'
    notify(order.user_id, title, message, 'order', url_for('customer.order_detail', order_id=order.id))
    db.session.commit()

    try:
        send_status_update_email(order, new_status)
    except Exception:
        current_app.logger.exception('Failed to send status update email for order %s', order.id)

    try:
        send_order_sms(order, new_status)
    except Exception:
        current_app.logger.exception('Failed to send status update SMS for order %s', order.id)


# ─────────────────────────────────────────
# INVENTORY ALERT TRIGGER
# (call after any stock update)
# ─────────────────────────────────────────
def check_and_send_inventory_alerts():
    """
    Check all active raw materials. If any are low/out-of-stock,
    send a digest email to all admin users.
    Should be called after order fulfilment or manual stock updates.
    """
    from models import RawMaterial, User
    from flask import current_app

    if not current_app.config.get('MAIL_ENABLED'):
        return

    alerts = []
    for m in RawMaterial.query.filter_by(is_active=True).all():
        if m.stock_status in ('low_stock', 'out_of_stock'):
            alerts.append({
                'name': m.name,
                'stock': float(m.stock),
                'unit': m.unit,
                'status': m.stock_status,
            })

    if not alerts:
        return

    admins = User.query.filter_by(role='admin', is_active=True).all()
    for admin in admins:
        if admin.email:
            send_low_stock_alert_email(admin.email, alerts)
