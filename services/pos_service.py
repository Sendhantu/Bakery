from models import Order, OrderItem, ProductVariant, Payment, db
from exceptions import ValidationError
from decimal import Decimal

class POSService:
    def create_pos_sale(self, variant_id, quantity, payment_mode='CASH', customer_phone='', actor_id=None):
        variant = ProductVariant.query.get_or_404(variant_id)
        unit_price = variant.price
        subtotal = unit_price * quantity
        # Minimal POS implementation: create order, items, payment, adjust stock
        with db.session.begin():
            # create walk-in customer placeholder
            from models import User
            customer = User.query.filter_by(email='walkin@sweetcrumbs.local').first()
            if not customer:
                customer = User(name='Walk-in Customer', email='walkin@sweetcrumbs.local', role='customer', is_active=True, phone=customer_phone or None)
                db.session.add(customer)
                db.session.flush()
            order = Order(order_number=Order.generate_order_number(), user_id=customer.id, source='POS', status='DELIVERED', payment_method=payment_mode, payment_status='PAID', subtotal=subtotal, total=subtotal)
            db.session.add(order)
            db.session.flush()
            db.session.add(OrderItem(order_id=order.id, product_id=variant.product_id, variant_id=variant.id, product_name=variant.product.name, variant_name=variant.name, quantity=quantity, unit_price=unit_price, subtotal=subtotal))
            variant.stock = max(0, int(variant.stock or 0) - quantity)
            payment = Payment(order_id=order.id, amount=subtotal, method=payment_mode)
            db.session.add(payment)
            db.session.flush()
            payment.transition_to('PAID', actor_id=actor_id, reason='pos_sale')
        return order
