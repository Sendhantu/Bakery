from decimal import Decimal

from bootstrap import get_container
from clock import utcnow
from models import (
    FinancialCategory,
    FinancialTransaction,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    StockMovement,
    Vendor,
    VendorProduct,
    db,
)


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _create_purchase_order(db_session, material, *, gstin=None, gst_rate=Decimal("18")):
    vendor = Vendor(
        name=f"Vendor {material.name}",
        contact_person="Procurement Contact",
        phone="9999990000",
        payment_terms="net 30",
        gstin=gstin,
        is_active=True,
    )
    db_session.add(vendor)
    db_session.flush()
    po = PurchaseOrder(
        vendor_id=vendor.id,
        status="ordered",
        order_date=utcnow().date(),
        expected_delivery_date=utcnow().date(),
        gst_rate_percent=gst_rate,
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        PurchaseOrderItem(
            purchase_order_id=po.id,
            raw_material_id=material.id,
            quantity=Decimal("5"),
            unit_cost=Decimal("40"),
        )
    )
    db_session.flush()
    return vendor, po


def test_purchase_order_received_creates_stock_and_finance_records(
    db_session,
    raw_material_factory,
):
    material = raw_material_factory(name="Vendor Flour", stock=Decimal("2"))
    vendor, po = _create_purchase_order(
        db_session,
        material,
        gstin="29ABCDE1234F1Z5",
        gst_rate=Decimal("18"),
    )

    result = get_container().purchase_order_service.receive_purchase_order(
        po, actor_id=None
    )
    db_session.commit()

    assert po.status == "received"
    assert po.received_at is not None
    assert material.stock == Decimal("7.00")
    movements = StockMovement.query.filter_by(
        raw_material_id=material.id,
        reason="purchase_order_received",
    ).all()
    assert len(movements) == 1
    assert movements[0].change_amount == Decimal("5.00")

    txn = result["transaction"]
    loaded_txn = db.session.get(FinancialTransaction, txn.id)
    assert loaded_txn.transaction_type == "expense"
    assert loaded_txn.reference_purchase_order_id == po.id
    assert loaded_txn.vendor_id == vendor.id
    assert loaded_txn.amount == Decimal("200.00")
    assert loaded_txn.tax_amount == Decimal("36.00")
    assert loaded_txn.category.code == "raw_material_purchase"
    assert loaded_txn.counterparty == vendor.name
    assert loaded_txn.is_auto_generated is True

    vendor_product = VendorProduct.query.filter_by(
        vendor_id=vendor.id,
        raw_material_id=material.id,
    ).first()
    assert vendor_product is not None
    assert vendor_product.typical_unit_cost == Decimal("40.00")
    assert vendor_product.last_unit_cost == Decimal("40.00")


def test_vendor_gstin_controls_input_tax_credit_in_gst_summary(
    db_session,
    raw_material_factory,
):
    finance = get_container().finance_service
    registered_material = raw_material_factory(name="Registered Butter", stock=0)
    unregistered_material = raw_material_factory(name="Unregistered Butter", stock=0)
    registered_vendor, registered_po = _create_purchase_order(
        db_session,
        registered_material,
        gstin="27ABCDE1234F1Z5",
        gst_rate=Decimal("12"),
    )
    unregistered_vendor, unregistered_po = _create_purchase_order(
        db_session,
        unregistered_material,
        gstin=None,
        gst_rate=Decimal("12"),
    )

    get_container().purchase_order_service.receive_purchase_order(
        registered_po,
        actor_id=None,
    )
    get_container().purchase_order_service.receive_purchase_order(
        unregistered_po,
        actor_id=None,
    )
    db_session.commit()

    registered_txn = FinancialTransaction.query.filter_by(
        reference_purchase_order_id=registered_po.id
    ).first()
    unregistered_txn = FinancialTransaction.query.filter_by(
        reference_purchase_order_id=unregistered_po.id
    ).first()

    assert registered_vendor.input_tax_credit_eligible is True
    assert registered_txn.tax_amount == Decimal("24.00")
    assert unregistered_vendor.input_tax_credit_eligible is False
    assert unregistered_txn.tax_amount == Decimal("0.00")

    today = utcnow().date()
    gst = finance.gst_summary(start_date=today, end_date=today)
    assert gst["gst_paid"] == Decimal("24.00")


def test_admin_vendor_and_purchase_order_pages_render(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = RawMaterial(
            name="Route Vendor Sugar",
            stock=Decimal("0"),
            reorder_level=Decimal("0"),
            unit="kg",
            cost_per_unit=Decimal("20"),
            is_active=True,
        )
        vendor = Vendor(
            name="Route Test Vendor",
            gstin="29ABCDE1234F1Z5",
            is_active=True,
        )
        db.session.add_all([material, vendor])
        db.session.commit()
        vendor_id = vendor.id
        material_id = material.id

    vendors_response = admin_client.get("/admin/vendors")
    assert vendors_response.status_code == 200
    assert b"Route Test Vendor" in vendors_response.data

    create_response = admin_client.post(
        "/admin/purchase-orders/new",
        data={
            "vendor_id": str(vendor_id),
            "order_date": utcnow().date().isoformat(),
            "expected_delivery_date": utcnow().date().isoformat(),
            "gst_rate_percent": "5",
            "raw_material_id[]": [str(material_id)],
            "quantity[]": ["3"],
            "unit_cost[]": ["20"],
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302

    with admin_client.application.app_context():
        po = PurchaseOrder.query.filter_by(vendor_id=vendor_id).first()
        assert po is not None
        assert po.items.count() == 1

    detail_response = admin_client.get(f"/admin/purchase-orders/{po.id}")
    assert detail_response.status_code == 200
    assert b"Route Test Vendor" in detail_response.data
    assert b"Mark Received" in detail_response.data
