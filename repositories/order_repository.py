from models import Order
from models import db


class OrderRepository:
    def get(self, order_id):
        return db.session.get(Order, order_id)

    def get_or_404(self, order_id):
        order = db.session.get(Order, order_id)
        if order is None:
            from flask import abort

            abort(404)
        return order

    def get_for_user_or_404(self, order_id, user_id):
        return Order.query.filter_by(id=order_id, user_id=user_id).first_or_404()

    def list_recent(self, limit=8):
        return Order.query.order_by(Order.placed_at.desc()).limit(limit).all()
