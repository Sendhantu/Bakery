from datetime import date

from sqlalchemy.exc import IntegrityError

from clock import utcnow
from models import (
    Notification,
    OccasionReminder,
    OccasionReminderLog,
    Product,
    db,
)


class OccasionReminderService:
    def send_due_reminders(self, today=None, campaign="annual_occasion"):
        today = today or utcnow().date()
        reminders = (
            OccasionReminder.query.filter_by(is_active=True)
            .order_by(OccasionReminder.occasion_date.asc())
            .all()
        )
        summary = {"sent": 0, "skipped": 0, "failed": 0}
        for reminder in reminders:
            target = self._next_annual_date(reminder.occasion_date, today)
            days_before = int(reminder.reminder_days_before or 10)
            if (target - today).days != days_before:
                summary["skipped"] += 1
                continue
            try:
                self._send_one(reminder, target.year, campaign=campaign)
                db.session.commit()
                summary["sent"] += 1
            except IntegrityError:
                db.session.rollback()
                summary["skipped"] += 1
            except Exception as exc:
                db.session.rollback()
                db.session.add(
                    OccasionReminderLog(
                        reminder_id=reminder.id,
                        user_id=reminder.user_id,
                        occasion_year=target.year,
                        campaign=campaign,
                        channel=reminder.preferred_channel,
                        status="failed",
                        error_details=str(exc),
                    )
                )
                db.session.commit()
                summary["failed"] += 1
        return summary

    def _send_one(self, reminder, occasion_year, *, campaign):
        products = (
            Product.query.filter_by(is_active=True)
            .order_by(Product.is_featured.desc(), Product.name.asc())
            .limit(3)
            .all()
        )
        product_names = ", ".join(product.name for product in products)
        message = (
            f"Reminder: {reminder.occasion_type} is coming up on "
            f"{reminder.occasion_date.strftime('%d %b')}. "
            "Browse the current bakery catalogue"
        )
        if reminder.marketing_consent and product_names:
            message += f" including {product_names}."
        else:
            message += "."
        db.session.add(
            Notification(
                user_id=reminder.user_id,
                title=f"{reminder.occasion_type} reminder",
                message=message,
                type="occasion",
                channel=reminder.preferred_channel,
                link="/products",
            )
        )
        db.session.add(
            OccasionReminderLog(
                reminder_id=reminder.id,
                user_id=reminder.user_id,
                occasion_year=occasion_year,
                campaign=campaign,
                channel=reminder.preferred_channel,
                status="sent",
                message=message,
            )
        )

    @staticmethod
    def _next_annual_date(occasion_date, today):
        target = date(today.year, occasion_date.month, occasion_date.day)
        if target < today:
            target = date(today.year + 1, occasion_date.month, occasion_date.day)
        return target
