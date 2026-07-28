from decimal import Decimal
import uuid

from clock import utcnow
from exceptions import ValidationError
from models import ProductVariant, User, db


class POSService:
    def create_pos_sale(
        self,
        variant_id,
        quantity,
        payment_mode="CASH",
        customer_phone="",
        actor_id=None,
    ):
        from bootstrap import get_container

        variant = db.session.get(ProductVariant, int(variant_id))
        if variant is None:
            raise ValidationError("POS variant not found.")

        customer = None
        customer_phone = (customer_phone or "").strip()
        if customer_phone:
            customer = User.query.filter_by(
                phone=customer_phone,
                role="customer",
                is_active=True,
            ).first()
        if customer is None:
            customer = User(
                name="Walk-in Customer",
                email=f"walkin-{uuid.uuid4().hex[:10]}@sweetcrumbs.local",
                role="customer",
                is_active=True,
                phone=customer_phone or None,
            )
            db.session.add(customer)
            db.session.flush()

        order_service = get_container().order_service
        line = order_service.build_line_from_variant(variant, quantity)
        subtotal = Decimal(str(line.unit_price)) * line.quantity
        store_details = get_container().app.config["STORE_DETAILS"]
        with db.session.begin_nested():
            creation = order_service.create_order(
                user_id=customer.id,
                branch_id=get_container().app.config.get("DEFAULT_BRANCH_ID"),
                lines=[line],
                subtotal=subtotal,
                total=subtotal,
                payment_method=payment_mode,
                payment_status="PAID",
                status="DELIVERED",
                channel="counter",
                source="POS",
                fulfillment_type="PICKUP",
                address_line1=store_details.get("address_line1", ""),
                address_line2=store_details.get("address_line2", ""),
                city=store_details.get("city", ""),
                pincode=store_details.get("pincode", ""),
                phone=customer_phone or store_details.get("phone_tel", ""),
                delivery_slot="Walk-in",
                delivery_date=utcnow().date(),
                actor_id=actor_id,
                payment_reason="pos_sale",
            )
        db.session.commit()
        return creation.order
