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
    assert gst["input_gst_recorded"] == Decimal("24.00")
    assert gst["non_creditable_input_gst"] == Decimal("24.00")
    assert gst["gst_paid"] == Decimal("0.00")


def test_purchase_order_receipt_deducts_tds_on_base_amount_only(
    db_session,
    raw_material_factory,
):
    finance = get_container().finance_service
    material = raw_material_factory(name="TDS Flour", stock=Decimal("0"))
    vendor, po = _create_purchase_order(
        db_session,
        material,
        gstin="29ABCDE1234F1Z5",
        gst_rate=Decimal("18"),
    )
    vendor.pan = "ABCDE1234F"
    vendor.tds_enabled = True
    vendor.tds_payment_type = "goods"
    vendor.tds_rate_percent = Decimal("0.10")
    vendor.tds_threshold_amount = Decimal("0")

    result = get_container().purchase_order_service.receive_purchase_order(
        po, actor_id=None
    )
    db_session.commit()

    loaded_txn = db.session.get(FinancialTransaction, result["transaction"].id)
    assert loaded_txn.amount == Decimal("200.00")
    assert loaded_txn.tax_amount == Decimal("36.00")
    assert loaded_txn.tds_withheld == Decimal("0.20")
    assert po.tds_applicable is True
    assert po.tds_section == "194Q"
    assert po.tds_base_amount == Decimal("200.00")
    assert po.tds_amount == Decimal("0.20")
    assert po.tds_deposit_due_date == finance.tds_deposit_due_date(po.received_at)
    assert "TDS from first invoice" in po.tds_reason


def test_purchase_order_tds_missing_pan_uses_twenty_percent(
    db_session,
    raw_material_factory,
):
    material = raw_material_factory(name="PAN Missing Flour", stock=Decimal("0"))
    vendor, po = _create_purchase_order(db_session, material, gst_rate=Decimal("0"))
    vendor.tds_enabled = True
    vendor.tds_payment_type = "professional_10"
    vendor.tds_threshold_amount = Decimal("0")

    get_container().purchase_order_service.receive_purchase_order(po, actor_id=None)
    db_session.commit()

    txn = FinancialTransaction.query.filter_by(reference_purchase_order_id=po.id).one()
    assert txn.tds_withheld == Decimal("40.00")
    assert po.tds_rate_percent == Decimal("20.000")
    assert "PAN missing" in po.tds_reason


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
            pan="ABCDE1234F",
            tds_enabled=True,
            tds_payment_type="goods",
            tds_threshold_amount=Decimal("0"),
            is_active=True,
        )
        db.session.add_all([material, vendor])
        db.session.commit()
        vendor_id = vendor.id
        material_id = material.id

    vendors_response = admin_client.get("/admin/vendors")
    assert vendors_response.status_code == 200
    assert b"Route Test Vendor" in vendors_response.data
    assert b"194Q" in vendors_response.data
    assert b"<div class=\"card-header\">Add Vendor</div>" not in vendors_response.data

    add_vendor_response = admin_client.get("/admin/vendors?add=1")
    assert add_vendor_response.status_code == 200
    assert b"<div class=\"card-header\">Add Vendor</div>" in add_vendor_response.data
    assert b"TDS Payment Type" in add_vendor_response.data

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

    updates_response = admin_client.get("/admin/purchase-orders/updates")
    assert updates_response.status_code == 200
    assert b"Purchase Updates" in updates_response.data
    assert b"Route Test Vendor" in updates_response.data
    assert b"Purchase order placed" in updates_response.data

    detail_response = admin_client.get(f"/admin/purchase-orders/{po.id}")
    assert detail_response.status_code == 200
    assert b"Route Test Vendor" in detail_response.data
    assert b"Mark Received" in detail_response.data
    assert b"Payment Method" in detail_response.data
    assert b"Purchase Updates" in detail_response.data
    assert b"Purchase order placed" in detail_response.data
    assert b"TDS Deduction" in detail_response.data

    receive_response = admin_client.post(
        f"/admin/purchase-orders/{po.id}/status",
        data={"action": "received", "payment_method": "UPI"},
        follow_redirects=False,
    )

    assert receive_response.status_code == 302
    with admin_client.application.app_context():
        transaction = FinancialTransaction.query.filter_by(
            reference_purchase_order_id=po.id
        ).first()
        assert transaction is not None
        assert transaction.payment_method == "UPI"
        assert transaction.tds_withheld == Decimal("0.06")

    vendor_detail_response = admin_client.get(f"/admin/vendors/{vendor_id}")
    assert vendor_detail_response.status_code == 200
    assert b"Payment Details" in vendor_detail_response.data
    assert b"UPI" in vendor_detail_response.data
    assert b"Paid" in vendor_detail_response.data
    assert b"TDS Withheld" in vendor_detail_response.data

    received_updates_response = admin_client.get("/admin/purchase-orders/updates")
    assert received_updates_response.status_code == 200
    assert b"Received" in received_updates_response.data
    assert b"Payment recorded" in received_updates_response.data


def test_purchase_order_requires_current_material_before_adding_next(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = RawMaterial(
            name="Sequential PO Material",
            stock=Decimal("0"),
            reorder_level=Decimal("0"),
            unit="kg",
            cost_per_unit=Decimal("20"),
            is_active=True,
        )
        vendor = Vendor(
            name="Sequential PO Vendor",
            is_active=True,
        )
        db.session.add_all([material, vendor])
        db.session.commit()
        vendor_id = vendor.id
        material_id = material.id

    form_response = admin_client.get("/admin/purchase-orders/new")
    assert form_response.status_code == 200
    assert b"data-add-po-line disabled" in form_response.data
    assert b"Fill the current material, quantity, and unit cost" in form_response.data

    response = admin_client.post(
        "/admin/purchase-orders/new",
        data={
            "vendor_id": str(vendor_id),
            "order_date": utcnow().date().isoformat(),
            "expected_delivery_date": utcnow().date().isoformat(),
            "gst_rate_percent": "0",
            "raw_material_id[]": ["", str(material_id)],
            "quantity[]": ["", "2"],
            "unit_cost[]": ["", "20"],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Complete each material line before adding another material." in response.data
    with admin_client.application.app_context():
        assert PurchaseOrder.query.filter_by(vendor_id=vendor_id).count() == 0
