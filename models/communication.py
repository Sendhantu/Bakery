from datetime import datetime
from .base import db

class Message(db.Model):
    __tablename__ = 'messages'
    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id    = db.Column(db.Integer, db.ForeignKey('orders.id'))
    content     = db.Column(db.Text, nullable=False)
    is_read     = db.Column(db.Boolean, default=False)
    sent_at     = db.Column(db.DateTime, default=datetime.utcnow)
    receiver    = db.relationship('User', foreign_keys=[receiver_id])


class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title      = db.Column(db.String(200))
    message    = db.Column(db.Text)
    type       = db.Column(db.String(50))
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link       = db.Column(db.String(255))


# ─────────────────────────────────────────
# EMAIL LOG  — tracks all sent emails
# ─────────────────────────────────────────
class EmailLog(db.Model):
    __tablename__ = 'email_log'
    id         = db.Column(db.Integer, primary_key=True)
    to_email   = db.Column(db.String(120), nullable=False)
    subject    = db.Column(db.String(200))
    body_key   = db.Column(db.String(50))   # e.g. 'order_placed', 'status_update'
    status     = db.Column(db.String(20), default='sent')   # sent / failed
    error      = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
