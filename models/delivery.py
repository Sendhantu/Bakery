from .base import db

class DeliveryAgent(db.Model):
    __tablename__ = 'delivery_agents'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'))
    name         = db.Column(db.String(100), nullable=False)
    phone        = db.Column(db.String(20))
    availability = db.Column(db.Boolean, default=True)
    user         = db.relationship('User', backref=db.backref('delivery_agent_profile', uselist=False), foreign_keys=[user_id])
    deliveries   = db.relationship('Delivery', backref='agent', lazy='dynamic')


class Delivery(db.Model):
    __tablename__ = 'deliveries'
    id             = db.Column(db.Integer, primary_key=True)
    order_id       = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    agent_id       = db.Column(db.Integer, db.ForeignKey('delivery_agents.id'))
    assigned_time  = db.Column(db.DateTime)
    delivered_time = db.Column(db.DateTime)
    notes          = db.Column(db.Text)
    status         = db.Column(db.String(30), default='ASSIGNED')
