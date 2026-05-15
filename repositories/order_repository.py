from models import Order


class OrderRepository:
    def get(self, order_id):
        return Order.query.get(order_id)

    def get_or_404(self, order_id):
        return Order.query.get_or_404(order_id)

    def get_for_user_or_404(self, order_id, user_id):
        return Order.query.filter_by(id=order_id, user_id=user_id).first_or_404()

    def list_recent(self, limit=8):
        return Order.query.order_by(Order.placed_at.desc()).limit(limit).all()
