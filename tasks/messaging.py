from datetime import datetime

from models import celery


@celery.task
def send_email(to, subject, html_body, text_body=None):
    from flask import current_app
    from models import EmailLog, db

    if not current_app.config.get("MAIL_ENABLED"):
        return False

    log = EmailLog(to_email=to, subject=subject, body_key="custom")
    try:
        from flask_mail import Message as MailMsg

        mail = current_app.extensions.get("mail")
        if mail is None:
            log.status = "failed"
            log.error = "Flask-Mail extension is not initialized."
            db.session.add(log)
            db.session.commit()
            current_app.logger.warning(
                "Email skipped because Flask-Mail is not initialized."
            )
            return False

        msg = MailMsg(
            subject=subject, recipients=[to], html=html_body, body=text_body or ""
        )
        mail.send(msg)
        log.status = "sent"
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as exc:
        log.status = "failed"
        log.error = str(exc)[:400]
        db.session.add(log)
        db.session.commit()
        current_app.logger.error("Email failed to %s: %s", to, exc)
        return False


@celery.task
def send_sms(to_number, message):
    from flask import current_app

    if not current_app.config.get("SMS_ENABLED"):
        return False
    try:
        from twilio.rest import Client

        client = Client(
            current_app.config["TWILIO_ACCOUNT_SID"],
            current_app.config["TWILIO_AUTH_TOKEN"],
        )
        client.messages.create(
            body=message, from_=current_app.config["TWILIO_FROM_NUMBER"], to=to_number
        )
        return True
    except Exception as exc:
        current_app.logger.error("SMS failed to %s: %s", to_number, exc)
        return False


def render_low_stock_digest(alerts):
    rows = "".join(
        f'<tr><td>{a["name"]}</td><td>{a["stock"]} {a["unit"]}</td>'
        f'<td style="color:{"red" if a["status"]=="out_of_stock" else "orange"}">'
        f'{"Out of Stock" if a["status"]=="out_of_stock" else "Low Stock"}</td></tr>'
        for a in alerts
    )
    return f"""
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
