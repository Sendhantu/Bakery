from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import random

from flask import current_app, has_app_context

from domains.orders import OrderStatusUpdated
from exceptions import ValidationError
from models import (
    GST_ECOMMERCE_OPERATOR_BY_SOURCE,
    GST_ECOMMERCE_ORDER_SOURCES,
    GST_LIABILITY_BAKERY,
    GST_LIABILITY_ECOMMERCE_OPERATOR,
    GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
    GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY,
    GST_ORDER_SOURCE_DIRECT_WEB_PICKUP,
    GST_ORDER_SOURCE_ECOMMERCE_SWIGGY,
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
    GST_ORDER_SOURCE_VALUES,
    GST_RETURN_ECOMMERCE_9_5,
    GST_RETURN_OUTWARD_SUPPLIES,
    GST_SUPPLY_RESTAURANT_SERVICE,
    Order,
    OrderItem,
    OrderStatusHistory,
    OrderStatusNotificationLog,
    Payment,
    ProductVariant,
    Notification,
    db,
)
from repositories import OrderRepository
from validators import ensure_order_status_transition
from clock import utcnow


@dataclass
class OrderCreationResult:
    order: Order
    payment: Payment
    stock_update_variant_ids: list[int]
    stock_update_material_ids: list[int]


@dataclass
class OrderLineInput:
    product_id: int
    variant_id: int | None
    product_name: str
    variant_name: str
    quantity: int
    unit_price: Decimal
    recipe_product: object | None = None

    @property
    def product(self):
        return self.recipe_product


class OrderService:
    def __init__(
        self,
        order_repository=None,
        event_bus=None,
        audit_service=None,
        loyalty_service=None,
    ):
        self.order_repository = order_repository or OrderRepository()
        self.event_bus = event_bus
        self.audit_service = audit_service
        self.loyalty_service = loyalty_service

    def create_order(
        self,
        *,
        user_id,
        lines,
        subtotal,
        total,
        payment_method="COD",
        payment_status="PENDING",
        status="PLACED",
        channel="online",
        source=None,
        branch_id=None,
        discount=0,
        loyalty_discount=0,
        gift_card_redemption_amount=0,
        gift_card_code=None,
        delivery_charge=0,
        gst_rate=5,
        gst_amount=0,
        gst_taxable_amount=None,
        cgst_amount=None,
        sgst_amount=None,
        gst_supply_type=GST_SUPPLY_RESTAURANT_SERVICE,
        gst_order_source=None,
        gst_liability_party=None,
        gst_return_bucket=None,
        gst_invoice_note=None,
        ecommerce_operator=None,
        ecommerce_tcs_amount=None,
        fulfillment_type="DELIVERY",
        address_line1="",
        address_line2="",
        city="",
        pincode="",
        phone="",
        delivery_latitude=None,
        delivery_longitude=None,
        serviceability_result=None,
        delivery_slot="",
        delivery_date=None,
        special_note=None,
        occasion=None,
        b2b_company_name=None,
        b2b_gstin=None,
        b2b_billing_address=None,
        b2b_state=None,
        b2b_pincode=None,
        b2b_po_number=None,
        b2b_department=None,
        b2b_billing_email=None,
        b2b_contact_person=None,
        b2b_invoice_notes=None,
        coupon_code=None,
        actor_id=None,
        payment_reason="order_created",
        transaction_id=None,
        expected_versions=None,
    ):
        """Create an order through the shared stock/payment/ledger pipeline.

        The caller owns the surrounding transaction and commit. Socket emits
        should happen only after that commit succeeds.
        """
        normalized_lines = self._normalize_lines(lines)
        if not normalized_lines:
            raise ValidationError("Add at least one item to the order.")

        expected_versions = expected_versions or {}
        stock_update_variant_ids = []
        stock_update_material_ids = []
        gst_context = self._normalize_gst_context(
            subtotal=subtotal,
            discount=discount,
            loyalty_discount=loyalty_discount,
            gst_rate=gst_rate,
            gst_amount=gst_amount,
            gst_taxable_amount=gst_taxable_amount,
            cgst_amount=cgst_amount,
            sgst_amount=sgst_amount,
            gst_supply_type=gst_supply_type,
            gst_order_source=gst_order_source,
            gst_liability_party=gst_liability_party,
            gst_return_bucket=gst_return_bucket,
            gst_invoice_note=gst_invoice_note,
            ecommerce_operator=ecommerce_operator,
            ecommerce_tcs_amount=ecommerce_tcs_amount,
            channel=channel,
            source=source,
            fulfillment_type=fulfillment_type,
        )

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=user_id,
            branch_id=branch_id,
            source=source or ("POS" if channel == "counter" else "WEB"),
            channel=channel,
            status=(status or "PLACED").upper(),
            subtotal=Decimal(str(subtotal or 0)),
            discount=Decimal(str(discount or 0)),
            loyalty_discount=Decimal(str(loyalty_discount or 0)),
            gift_card_redemption_amount=Decimal(str(gift_card_redemption_amount or 0)),
            gift_card_code=(gift_card_code or "").strip().upper() or None,
            delivery_charge=Decimal(str(delivery_charge or 0)),
            gst_rate=Decimal(str(gst_rate or 5)),
            gst_amount=(
                gst_context["cgst_amount"] + gst_context["sgst_amount"]
            ).quantize(Decimal("0.01")),
            gst_taxable_amount=gst_context["gst_taxable_amount"],
            cgst_amount=gst_context["cgst_amount"],
            sgst_amount=gst_context["sgst_amount"],
            gst_supply_type=gst_context["gst_supply_type"],
            gst_order_source=gst_context["gst_order_source"],
            gst_liability_party=gst_context["gst_liability_party"],
            gst_return_bucket=gst_context["gst_return_bucket"],
            gst_invoice_note=gst_context["gst_invoice_note"],
            ecommerce_operator=gst_context["ecommerce_operator"],
            ecommerce_tcs_amount=gst_context["ecommerce_tcs_amount"],
            total=Decimal(str(total or 0)),
            fulfillment_type=(fulfillment_type or "DELIVERY").upper(),
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            pincode=pincode,
            phone=phone,
            delivery_latitude=delivery_latitude,
            delivery_longitude=delivery_longitude,
            serviceability_status=(
                getattr(serviceability_result, "status", None)
                if serviceability_result is not None
                else None
            ),
            serviceability_message=(
                getattr(serviceability_result, "message", None)
                if serviceability_result is not None
                else None
            ),
            serviceability_distance_km=(
                getattr(serviceability_result, "distance_km", None)
                if serviceability_result is not None
                else None
            ),
            serviceability_rule_source=(
                getattr(serviceability_result, "rule_source", None)
                if serviceability_result is not None
                else None
            ),
            delivery_slot=delivery_slot,
            delivery_date=delivery_date,
            special_note=special_note,
            occasion=occasion,
            b2b_company_name=(b2b_company_name or "").strip() or None,
            b2b_gstin=(b2b_gstin or "").strip().upper() or None,
            b2b_billing_address=(b2b_billing_address or "").strip() or None,
            b2b_state=(b2b_state or "").strip() or None,
            b2b_pincode=(b2b_pincode or "").strip() or None,
            b2b_po_number=(b2b_po_number or "").strip() or None,
            b2b_department=(b2b_department or "").strip() or None,
            b2b_billing_email=(b2b_billing_email or "").strip() or None,
            b2b_contact_person=(b2b_contact_person or "").strip() or None,
            b2b_invoice_notes=(b2b_invoice_notes or "").strip() or None,
            payment_method=(payment_method or "COD").upper(),
            payment_status="PENDING",
            coupon_code=coupon_code,
        )
        db.session.add(order)
        db.session.flush()
        self._record_status_history(
            order,
            None,
            order.status,
            actor_id=actor_id,
            source=payment_reason or "order_created",
            customer_note="Order placed successfully.",
        )

        for line in normalized_lines:
            db.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=line.product_id,
                    variant_id=line.variant_id,
                    product_name=line.product_name,
                    variant_name=line.variant_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    subtotal=line.unit_price * line.quantity,
                )
            )
            if line.variant_id:
                variant = db.session.get(
                    ProductVariant,
                    line.variant_id,
                    with_for_update=True,
                )
                if variant is None:
                    raise ValidationError("Product variant is no longer available.")
                expected_version = expected_versions.get(str(line.variant_id))
                if expected_version is None:
                    expected_version = expected_versions.get(line.variant_id)
                if expected_version not in {None, ""}:
                    from exceptions import ConflictError
                    from utils.optimistic import assert_version

                    try:
                        assert_version(
                            variant,
                            expected_version,
                            entity_name="ProductVariant",
                        )
                    except ConflictError as exc:
                        raise ValidationError(
                            "Version conflict: variant stock changed by another user."
                        ) from exc
                if int(variant.stock or 0) < line.quantity:
                    raise ValidationError(
                        f"Sorry, {line.product_name} is out of stock."
                    )
                variant.stock = int(variant.stock or 0) - line.quantity
                variant.version = int(variant.version or 0) + 1
                stock_update_variant_ids.append(variant.id)

        stock_update_material_ids = (
            self._inventory_service().deduct_order_raw_materials(
                normalized_lines,
                order,
                created_by=actor_id,
            )
        )

        payment = Payment(
            order_id=order.id,
            amount=Decimal(str(total or 0)),
            status="PENDING",
            method=order.payment_method,
            transaction_id=transaction_id or f"TXN{random.randint(100000,999999)}",
        )
        db.session.add(payment)
        db.session.flush()

        if (payment_status or "").upper() == "PAID":
            payment.transition_to("PAID", actor_id=actor_id, reason=payment_reason)
            if order.status == "DELIVERED":
                self._award_loyalty_points(order)
        else:
            order.payment_status = (payment_status or "PENDING").upper()

        return OrderCreationResult(
            order=order,
            payment=payment,
            stock_update_variant_ids=stock_update_variant_ids,
            stock_update_material_ids=stock_update_material_ids,
        )

    def _normalize_gst_context(
        self,
        *,
        subtotal,
        discount,
        loyalty_discount,
        gst_rate,
        gst_amount,
        gst_taxable_amount,
        cgst_amount,
        sgst_amount,
        gst_supply_type,
        gst_order_source,
        gst_liability_party,
        gst_return_bucket,
        gst_invoice_note,
        ecommerce_operator,
        ecommerce_tcs_amount,
        channel,
        source,
        fulfillment_type,
    ):
        source_value = self._normalize_gst_order_source(
            gst_order_source,
            channel=channel,
            source=source,
            fulfillment_type=fulfillment_type,
        )
        liability_party = (
            (gst_liability_party or "").strip().upper()
            or (
                GST_LIABILITY_ECOMMERCE_OPERATOR
                if source_value in GST_ECOMMERCE_ORDER_SOURCES
                else GST_LIABILITY_BAKERY
            )
        )
        taxable = (
            Decimal(str(gst_taxable_amount))
            if gst_taxable_amount is not None
            else (
                Decimal(str(subtotal or 0))
                - Decimal(str(discount or 0))
                - Decimal(str(loyalty_discount or 0))
            )
        )
        taxable = max(taxable, Decimal("0")).quantize(Decimal("0.01"))
        gst_total = Decimal(str(gst_amount or 0)).quantize(Decimal("0.01"))
        if gst_total <= 0:
            rate = Decimal(str(gst_rate or 0))
            gst_total = (taxable * rate / Decimal("100")).quantize(Decimal("0.01"))
        cgst = (
            Decimal(str(cgst_amount)).quantize(Decimal("0.01"))
            if cgst_amount is not None
            else (gst_total / Decimal("2")).quantize(Decimal("0.01"))
        )
        sgst = (
            Decimal(str(sgst_amount)).quantize(Decimal("0.01"))
            if sgst_amount is not None
            else (gst_total - cgst).quantize(Decimal("0.01"))
        )
        return_bucket = (
            (gst_return_bucket or "").strip().upper()
            or (
                GST_RETURN_ECOMMERCE_9_5
                if liability_party == GST_LIABILITY_ECOMMERCE_OPERATOR
                else GST_RETURN_OUTWARD_SUPPLIES
            )
        )
        operator = (
            (ecommerce_operator or "").strip().upper()
            or GST_ECOMMERCE_OPERATOR_BY_SOURCE.get(source_value)
        )
        ecommerce_tcs_rate = (
            Decimal(str(current_app.config.get("GST_ECOMMERCE_TCS_RATE", 1)))
            if has_app_context()
            else Decimal("1")
        )
        tcs_amount = (
            Decimal(str(ecommerce_tcs_amount)).quantize(Decimal("0.01"))
            if ecommerce_tcs_amount is not None
            else (
                taxable * ecommerce_tcs_rate / Decimal("100")
                if liability_party == GST_LIABILITY_ECOMMERCE_OPERATOR
                else Decimal("0")
            ).quantize(Decimal("0.01"))
        )
        note = (gst_invoice_note or "").strip() or None
        if not note and liability_party == GST_LIABILITY_ECOMMERCE_OPERATOR:
            note = (
                "Tax to be deposited by E-commerce Operator under Section 9(5) "
                "of the CGST Act."
            )
        return {
            "gst_taxable_amount": taxable,
            "cgst_amount": cgst,
            "sgst_amount": sgst,
            "gst_supply_type": (
                (gst_supply_type or GST_SUPPLY_RESTAURANT_SERVICE).strip().upper()
            ),
            "gst_order_source": source_value,
            "gst_liability_party": liability_party,
            "gst_return_bucket": return_bucket,
            "gst_invoice_note": note,
            "ecommerce_operator": operator,
            "ecommerce_tcs_amount": tcs_amount,
        }

    def _normalize_gst_order_source(
        self,
        value=None,
        *,
        channel="online",
        source=None,
        fulfillment_type="DELIVERY",
    ):
        explicit = (value or "").strip().upper()
        if explicit in GST_ORDER_SOURCE_VALUES:
            return explicit
        source_upper = (source or "").strip().upper()
        if source_upper in {"SWIGGY", "ECOMMERCE_SWIGGY"}:
            return GST_ORDER_SOURCE_ECOMMERCE_SWIGGY
        if source_upper in {"ZOMATO", "ECOMMERCE_ZOMATO"}:
            return GST_ORDER_SOURCE_ECOMMERCE_ZOMATO
        if (channel or "").strip().lower() == "counter":
            return GST_ORDER_SOURCE_COUNTER_TAKEAWAY
        if (fulfillment_type or "").strip().upper() == "PICKUP":
            return GST_ORDER_SOURCE_DIRECT_WEB_PICKUP
        return GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY

    def build_line_from_cart_item(self, cart_item, unit_price=None):
        variant = cart_item.variant
        product = cart_item.product
        if product is None:
            raise ValidationError("A cart item references an unavailable product.")
        resolved_price = (
            Decimal(str(unit_price))
            if unit_price is not None
            else self._resolve_price(product, variant)
        )
        return OrderLineInput(
            product_id=cart_item.product_id,
            variant_id=cart_item.variant_id,
            product_name=product.name,
            variant_name=variant.name if variant else "",
            quantity=max(1, int(cart_item.quantity or 1)),
            unit_price=resolved_price,
            recipe_product=product,
        )

    def build_line_from_variant(self, variant, quantity, unit_price=None):
        if variant is None or variant.product is None:
            raise ValidationError("Product variant is no longer available.")
        resolved_price = (
            Decimal(str(unit_price))
            if unit_price is not None
            else self._resolve_price(variant.product, variant)
        )
        return OrderLineInput(
            product_id=variant.product_id,
            variant_id=variant.id,
            product_name=variant.product.name,
            variant_name=variant.name,
            quantity=max(1, int(quantity or 1)),
            unit_price=resolved_price,
            recipe_product=variant.product,
        )

    def update_order_status(
        self,
        order_id,
        new_status,
        actor="admin",
        actor_id=None,
        expected_version=None,
        customer_note=None,
        internal_note=None,
        delay_reason=None,
        delayed_until=None,
    ):
        order = self.order_repository.get_or_404(order_id)
        # optimistic check if caller provided expected_version
        from utils.optimistic import assert_version

        assert_version(order, expected_version, entity_name="Order")
        status = ensure_order_status_transition(order.status, new_status, actor=actor)
        old_status = order.status

        with db.session.begin_nested():
            order.status = status
            if status == "DELAYED":
                if not delay_reason:
                    raise ValidationError("Please provide a delay reason.")
                if delayed_until is None:
                    raise ValidationError("Please provide the updated estimated time.")
                order.delay_reason = delay_reason
                order.delayed_until = delayed_until
                order.estimated_ready_at = delayed_until
            if customer_note:
                order.status_note = customer_note
            order.mark_status_change()
            self._record_status_history(
                order,
                old_status,
                status,
                actor_id=actor_id,
                source=actor,
                customer_note=customer_note,
                internal_note=internal_note,
            )
            self._record_status_notification(order, status, channel="in_app")
            self._sync_delivery_status(order, status)
            if self.audit_service is not None:
                self.audit_service.log(
                    actor_id,
                    "order_status_changed",
                    "Order",
                    order.id,
                    before={"status": old_status},
                    after={"status": status, "actor": actor},
                    branch_id=order.branch_id,
                    change_summary=f"Order status changed from {old_status} to {status}",
                )
            if status == "DELIVERED":
                self._award_loyalty_points(order)
        db.session.commit()

        if self.event_bus is not None:
            self.event_bus.publish(
                OrderStatusUpdated(
                    order_id=order.id,
                    old_status=old_status,
                    new_status=status,
                )
            )
        return order

    def _record_status_history(
        self,
        order,
        previous_status,
        new_status,
        *,
        actor_id=None,
        source="system",
        customer_note=None,
        internal_note=None,
    ):
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                previous_status=previous_status,
                new_status=new_status,
                updated_by=actor_id,
                update_source=source or "system",
                customer_note=customer_note,
                internal_note=internal_note,
                related_employee_id=actor_id,
            )
        )

    def _record_status_notification(self, order, status, *, channel="in_app"):
        exists = OrderStatusNotificationLog.query.filter_by(
            order_id=order.id,
            status=status,
            channel=channel,
        ).first()
        if exists is not None:
            return
        db.session.add(
            OrderStatusNotificationLog(
                order_id=order.id,
                status=status,
                channel=channel,
                delivery_status="queued" if channel != "in_app" else "sent",
                template="order_status_update",
            )
        )
        db.session.add(
            Notification(
                user_id=order.user_id,
                title=f"Order {order.status_label}",
                message=f"Order #{order.order_number} is now {order.status_label}.",
                type="order",
                priority="normal",
                channel=channel,
                link=f"/track/{order.tracking_token}",
            )
        )

    def _award_loyalty_points(self, order):
        service = self.loyalty_service
        if service is None:
            try:
                from bootstrap import get_container

                service = get_container().loyalty_service
            except Exception:
                service = None
        if service is None:
            return 0
        try:
            return service.award_order_points(order)
        except Exception:
            return 0

    def _sync_delivery_status(self, order, new_status):
        delivery = order.delivery
        if delivery is None:
            return

        agent = delivery.agent
        if new_status == "DELIVERED":
            delivery.status = "DELIVERED"
            delivery.delivered_time = utcnow()
            delivery.last_status_at = utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = True
            return

        delivery.delivered_time = None
        if new_status == "OUT_FOR_DELIVERY":
            delivery.status = "OUT_FOR_DELIVERY"
            delivery.last_status_at = utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False
        elif new_status == "PACKED":
            delivery.status = "PACKED"
            delivery.last_status_at = utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False
        elif new_status == "CANCELLED":
            delivery.status = "CANCELLED"
            delivery.last_status_at = utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = True
        else:
            delivery.status = "ASSIGNED"
            delivery.last_status_at = utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False

    def _normalize_lines(self, lines):
        normalized = []
        for line in lines or []:
            if isinstance(line, OrderLineInput):
                normalized.append(line)
            elif hasattr(line, "product_id") and hasattr(line, "quantity"):
                product = getattr(line, "product", None)
                variant = getattr(line, "variant", None)
                normalized.append(
                    OrderLineInput(
                        product_id=line.product_id,
                        variant_id=getattr(line, "variant_id", None),
                        product_name=getattr(product, "name", "") or "",
                        variant_name=getattr(variant, "name", "") if variant else "",
                        quantity=max(1, int(line.quantity or 1)),
                        unit_price=Decimal(str(getattr(line, "unit_price", 0) or 0)),
                        recipe_product=product,
                    )
                )
            else:
                raise ValidationError("Invalid order line item.")
        return normalized

    def _resolve_price(self, product, variant=None):
        try:
            from bootstrap import get_container

            return Decimal(
                str(
                    get_container().pricing_service.resolve_product_price(
                        product, variant
                    )["price"]
                )
            )
        except Exception:
            if variant is not None:
                return Decimal(str(variant.price or 0))
            return Decimal(str(product.base_price or 0))

    def _inventory_service(self):
        try:
            from bootstrap import get_container

            return get_container().inventory_service
        except Exception:
            from services.inventory_service import InventoryService

            return InventoryService()
