from .base import db

class DeliveryAgent(db.Model):
    __tablename__ = 'delivery_agents'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'))
    branch_id    = db.Column(db.Integer, db.ForeignKey('branches.id'))
    name         = db.Column(db.String(100), nullable=False)
    phone        = db.Column(db.String(20))
    availability = db.Column(db.Boolean, default=True)
    current_latitude = db.Column(db.Float)
    current_longitude = db.Column(db.Float)
    last_location_at = db.Column(db.DateTime)
    user         = db.relationship('User', backref=db.backref('delivery_agent_profile', uselist=False), foreign_keys=[user_id])
    deliveries   = db.relationship('Delivery', backref='agent', lazy='dynamic')
    branch       = db.relationship('Branch', backref='delivery_agents')


class Delivery(db.Model):
    __tablename__ = 'deliveries'
    id             = db.Column(db.Integer, primary_key=True)
    order_id       = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    agent_id       = db.Column(db.Integer, db.ForeignKey('delivery_agents.id'))
    branch_id      = db.Column(db.Integer, db.ForeignKey('branches.id'))
    route_plan_id  = db.Column(db.Integer, db.ForeignKey('delivery_route_plans.id'))
    assigned_time  = db.Column(db.DateTime)
    delivered_time = db.Column(db.DateTime)
    notes          = db.Column(db.Text)
    status         = db.Column(db.String(30), default='ASSIGNED')
    qr_token       = db.Column(db.String(80), unique=True)
    qr_verified_at = db.Column(db.DateTime)
    last_status_at = db.Column(db.DateTime)
    eta_minutes    = db.Column(db.Integer)
    version        = db.Column(db.Integer, default=1, nullable=False)

    branch = db.relationship('Branch', backref='deliveries')
    __table_args__ = (
        db.Index('idx_delivery_agent', 'agent_id'),
        db.Index('idx_delivery_status', 'status'),
        db.Index('idx_delivery_order', 'order_id'),
    )
