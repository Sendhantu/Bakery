from decimal import Decimal

from models import (
    AuditLog,
    FinancialCategory,
    FinancialTransaction,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductMaterial,
    ProductVariant,
    RawMaterial,
    Refund,
    StockMovement,
    User,
    db,
)
from services.finance_service import FinanceService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_admin_user(app, email, tier, password="AdminTier1"):
    with app.app_context():
        user = User(
            name=f"{tier.title()} User",
            email=email,
            role="admin",
            admin_tier=tier,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def create_order_with_deducted_stock(app, *, paid=False, status="PREPARING"):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        product = Product(
            name=f"Cancel Cake {paid}", base_price=Decimal("100"), is_active=True
        )
        variant = ProductVariant(
            product=product, name="Slice", price=Decimal("100"), stock=5
        )
        material = RawMaterial(
            name=f"Cancel Flour {paid}",
            unit="kg",
            stock=Decimal("10"),
            reorder_level=Decimal("2"),
            cost_per_unit=Decimal("40"),
        )
        db.session.add_all([product, variant, material])
        db.session.flush()
        db.session.add(
            ProductMaterial(
                product_id=product.id,
                raw_material_id=material.id,
                quantity_required=Decimal("2"),
            )
        )
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status=status,
            subtotal=Decimal("200"),
            total=Decimal("200"),
            payment_status="PENDING",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
        )
        db.session.add(order)
        db.session.flush()
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            variant_id=variant.id,
            product_name=product.name,
            variant_name=variant.name,
            quantity=2,
            unit_price=Decimal("100"),
            subtotal=Decimal("200"),
        )
        db.session.add(item)
        variant.stock -= 2
        db.session.flush()
        app.extensions[
            "service_container"
        ].inventory_service.deduct_order_raw_materials(
            [item],
            order,
            created_by=None,
        )
        payment = Payment(
            order_id=order.id, amount=Decimal("200"), status="PENDING", method="COD"
        )
        db.session.add(payment)
        db.session.flush()
        if paid:
            FinanceService().ensure_default_categories()
            payment.transition_to("PAID", reason="test")
        db.session.commit()
        return {
            "order_id": order.id,
            "variant_id": variant.id,
            "material_id": material.id,
        }


def test_admin_cancel_unpaid_order_reverses_stock_with_append_only_movements(
    admin_client,
):
    ids = create_order_with_deducted_stock(admin_client.application, paid=False)
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        f"/admin/orders/{ids['order_id']}/cancel-refund",
        data={
            "action": "cancel",
            "reason": "Duplicate order",
            "stock_handling": "reverse",
            "confirm_reversal": "yes",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with admin_client.application.app_context():
        order = db.session.get(Order, ids["order_id"])
        variant = db.session.get(ProductVariant, ids["variant_id"])
        material = db.session.get(RawMaterial, ids["material_id"])
        assert order.status == "CANCELLED"
        assert order.payment_status == "CANCELLED"
        assert variant.stock == 5
        assert Decimal(str(material.stock)) == Decimal("10.00")
        assert (
            StockMovement.query.filter_by(
                reference_order_id=order.id,
                reason="order_deduction",
            ).count()
            == 1
        )
        reversal = StockMovement.query.filter_by(
            reference_order_id=order.id,
            reason="order_cancellation_reversal",
        ).first()
        assert reversal is not None
        assert Decimal(str(reversal.change_amount)) == Decimal("4.00")
        assert (
            AuditLog.query.filter_by(
                action="order_cancelled",
                entity_type="Order",
                entity_id=str(order.id),
            ).first()
            is not None
        )


def test_admin_refund_paid_order_creates_refund_expense_without_stock_reversal(
    admin_client,
):
    ids = create_order_with_deducted_stock(admin_client.application, paid=True)
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        f"/admin/orders/{ids['order_id']}/cancel-refund",
        data={
            "action": "refund",
            "reason": "Customer requested refund",
            "stock_handling": "no_reverse",
            "confirm_reversal": "yes",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with admin_client.application.app_context():
        order = db.session.get(Order, ids["order_id"])
        material = db.session.get(RawMaterial, ids["material_id"])
        refund_category = FinancialCategory.query.filter_by(code="refund").first()
        assert order.status == "REFUNDED"
        assert order.payment_status == "REFUNDED"
        assert Decimal(str(material.stock)) == Decimal("6.00")
        assert (
            Refund.query.filter_by(order_id=order.id, status="COMPLETED").first()
            is not None
        )
        refund_txn = FinancialTransaction.query.filter_by(
            reference_order_id=order.id,
            transaction_type="expense",
            category_id=refund_category.id,
        ).first()
        assert refund_txn is not None
        assert Decimal(str(refund_txn.amount)) == Decimal("200")
        assert Decimal(str(refund_txn.tax_amount or 0)) > Decimal("0")
        assert (
            StockMovement.query.filter_by(
                reference_order_id=order.id,
                reason="order_cancellation_reversal",
            ).count()
            == 0
        )
        assert (
            AuditLog.query.filter_by(
                action="order_refunded",
                entity_type="Order",
                entity_id=str(order.id),
            ).first()
            is not None
        )


def test_delivered_order_is_not_refunded_by_standard_path(admin_client):
    ids = create_order_with_deducted_stock(
        admin_client.application, paid=True, status="DELIVERED"
    )
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        f"/admin/orders/{ids['order_id']}/cancel-refund",
        data={
            "action": "refund",
            "reason": "Late claim",
            "stock_handling": "no_reverse",
            "confirm_reversal": "yes",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with admin_client.application.app_context():
        order = db.session.get(Order, ids["order_id"])
        assert order.status == "DELIVERED"
        assert Refund.query.filter_by(order_id=order.id).count() == 0


def test_staff_tier_cannot_authorize_refund(admin_client):
    ids = create_order_with_deducted_stock(admin_client.application, paid=True)
    create_admin_user(admin_client.application, "staff.refund@bakery.com", "staff")
    sign_in(admin_client, "staff.refund@bakery.com", "AdminTier1")

    response = admin_client.post(
        f"/admin/orders/{ids['order_id']}/cancel-refund",
        data={
            "action": "refund",
            "reason": "Not allowed",
            "stock_handling": "no_reverse",
            "confirm_reversal": "yes",
        },
    )

    assert response.status_code == 403
