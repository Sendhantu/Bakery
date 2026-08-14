from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from bootstrap import get_container
from clock import utcnow
from models import (
    AuditLog,
    FinancialTransaction,
    MaterialBatch,
    MaterialDocument,
    PurchaseOrder,
    PurchaseOrderItem,
    ProductMaterial,
    RawMaterial,
    StockMovement,
    Vendor,
    db,
)


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_admin_user(app, email, tier, password="AdminTier1"):
    from models import User

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


def create_material(db_session, *, name=None, stock=Decimal("10"), reorder=Decimal("2"), sku=None):
    material = RawMaterial(
        name=name or f"Test Flour {utcnow().microsecond}",
        sku=sku,
        stock=stock,
        reorder_level=reorder,
        unit="kg",
        cost_per_unit=Decimal("40"),
        category="Bakery",
        storage_location="Dry store",
        is_active=True,
    )
    db_session.add(material)
    db_session.commit()
    return material


def create_received_po(db_session, material, *, quantity=Decimal("5"), unit_cost=Decimal("40"), payment_amount=None):
    vendor = Vendor(
        name=f"Vendor {utcnow().microsecond}",
        contact_person="Contact",
        phone="9999990000",
        is_active=True,
    )
    db_session.add(vendor)
    db_session.flush()
    po = PurchaseOrder(
        vendor_id=vendor.id,
        status="ordered",
        order_date=utcnow().date(),
        gst_rate_percent=Decimal("0"),
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        PurchaseOrderItem(
            purchase_order_id=po.id,
            raw_material_id=material.id,
            quantity=quantity,
            unit_cost=unit_cost,
        )
    )
    db_session.flush()
    get_container().purchase_order_service.receive_purchase_order(
        po, actor_id=None, payment_amount=payment_amount
    )
    db_session.commit()
    return vendor, po


def test_raw_materials_list_renders_with_summary_cards_and_filters(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        low = RawMaterial(
            name="Low Stock Sugar",
            stock=Decimal("1"),
            reorder_level=Decimal("5"),
            unit="kg",
            cost_per_unit=Decimal("20"),
            category="Bakery",
            is_active=True,
        )
        out = RawMaterial(
            name="Out Flour",
            stock=Decimal("0"),
            reorder_level=Decimal("2"),
            unit="kg",
            cost_per_unit=Decimal("30"),
            is_active=True,
        )
        db.session.add_all([low, out])
        db.session.commit()

    response = admin_client.get("/admin/raw-materials")
    assert response.status_code == 200
    assert b"Raw Materials" in response.data
    assert b"Total Materials" in response.data
    assert b"Low Stock" in response.data
    assert b"Out of Stock" in response.data
    assert b"Expiring Soon" in response.data
    assert b"Inventory Value" in response.data
    assert b"Low Stock Sugar" in response.data

    low_response = admin_client.get("/admin/raw-materials?status=low_stock")
    assert low_response.status_code == 200
    assert b"Low Stock Sugar" in low_response.data
    assert b"Out Flour" not in low_response.data

    search_response = admin_client.get("/admin/raw-materials?q=Flour")
    assert search_response.status_code == 200
    assert b"Out Flour" in search_response.data
    assert b"Low Stock Sugar" not in search_response.data


def test_raw_materials_list_shows_delete_for_authorized_managers(admin_client):
    create_admin_user(admin_client.application, "manager-delete@bakery.com", "manager")
    sign_in(admin_client, "manager-delete@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(
            db.session,
            name="Delete Button Flour",
            stock=Decimal("0"),
        )
        material_id = material.id

    response = admin_client.get("/admin/raw-materials")
    assert response.status_code == 200
    assert b"Delete Button Flour" in response.data
    assert f"/admin/raw-materials/{material_id}/delete".encode() in response.data
    assert b"data-confirm=\"Delete raw material" in response.data


def test_staff_cannot_see_or_post_raw_material_delete(admin_client):
    create_admin_user(admin_client.application, "staff-delete@bakery.com", "staff")
    sign_in(admin_client, "staff-delete@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(
            db.session,
            name="Staff Hidden Delete Flour",
            stock=Decimal("0"),
        )
        material_id = material.id

    response = admin_client.get("/admin/raw-materials")
    assert response.status_code == 200
    assert f"/admin/raw-materials/{material_id}/delete".encode() not in response.data
    delete_response = admin_client.post(
        f"/admin/raw-materials/{material_id}/delete",
        follow_redirects=False,
    )
    assert delete_response.status_code == 403
    with admin_client.application.app_context():
        assert db.session.get(RawMaterial, material_id) is not None


def test_unreferenced_zero_stock_raw_material_can_be_deleted(admin_client):
    create_admin_user(admin_client.application, "manager-hard-delete@bakery.com", "manager")
    sign_in(admin_client, "manager-hard-delete@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(
            db.session,
            name="Unused Delete Flour",
            stock=Decimal("0"),
            reorder=Decimal("0"),
        )
        material_id = material.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/delete",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Unused Delete Flour deleted" in response.data
    with admin_client.application.app_context():
        assert db.session.get(RawMaterial, material_id) is None


def test_referenced_raw_material_is_paused_instead_of_deleted(admin_client):
    create_admin_user(admin_client.application, "manager-soft-delete@bakery.com", "manager")
    sign_in(admin_client, "manager-soft-delete@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        from models import Category, Product

        material = create_material(
            db.session,
            name="Referenced Delete Flour",
            stock=Decimal("0"),
            reorder=Decimal("0"),
        )
        category = Category(name="Referenced Raw Material Category", icon="cake")
        product = Product(
            name="Referenced Raw Material Product",
            base_price=Decimal("100"),
            category=category,
            is_active=True,
        )
        db.session.add_all([category, product])
        db.session.flush()
        db.session.add(
            ProductMaterial(
                product_id=product.id,
                raw_material_id=material.id,
                quantity_required=Decimal("1"),
            )
        )
        db.session.commit()
        material_id = material.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/delete",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"paused instead of deleted" in response.data
    with admin_client.application.app_context():
        material = db.session.get(RawMaterial, material_id)
        assert material is not None
        assert material.is_active is False


def test_raw_material_detail_is_read_only_for_staff(admin_client):
    create_admin_user(admin_client.application, "staff@bakery.com", "staff")
    sign_in(admin_client, "staff@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session)
        material_id = material.id

    response = admin_client.get(f"/admin/raw-materials/{material_id}")
    assert response.status_code == 200
    assert material.name.encode() in response.data
    assert b"Record Stock Change" not in response.data
    assert b"Edit Details" not in response.data
    assert b"Change Status" not in response.data

    post_response = admin_client.post(
        f"/admin/raw-materials/{material_id}/stock",
        data={"action": "add", "quantity": "5"},
        follow_redirects=False,
    )
    assert post_response.status_code == 403


def test_raw_material_detail_orders_review_history_before_management(admin_client):
    create_admin_user(admin_client.application, "manager-detail-order@bakery.com", "manager")
    sign_in(admin_client, "manager-detail-order@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Ordered Detail Flour")
        material_id = material.id

    response = admin_client.get(f"/admin/raw-materials/{material_id}")
    assert response.status_code == 200
    markers = [
        b'id="summary"',
        b'id="details"',
        b'id="batches"',
        b'id="purchases"',
        b'id="movements"',
        b'id="documents"',
        b'id="management"',
    ]
    positions = [response.data.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert response.data.index(b"Inventory Management") < response.data.index(
        b"Record Stock Change"
    )
    assert response.data.index(b"Documents &amp; Attachments") < response.data.index(
        b"Inventory Management"
    )


def test_staff_cannot_edit_details_or_toggle(admin_client):
    create_admin_user(admin_client.application, "staff@bakery.com", "staff")
    sign_in(admin_client, "staff@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Staff Edit Flour")
        material_id = material.id

    edit_response = admin_client.post(
        f"/admin/raw-materials/{material_id}/details",
        data={"name": "Hacked Name", "unit": "kg"},
        follow_redirects=False,
    )
    assert edit_response.status_code == 403
    toggle_response = admin_client.post(
        f"/admin/raw-materials/{material_id}/toggle",
        follow_redirects=False,
    )
    assert toggle_response.status_code == 403
    with admin_client.application.app_context():
        assert db.session.get(RawMaterial, material_id).name == "Staff Edit Flour"


def test_manager_records_stock_actions_with_movements(admin_client):
    create_admin_user(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Action Flour", stock=Decimal("10"))
        material_id = material.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/stock",
        data={"action": "usage", "quantity": "2", "notes": "Baked cakes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with admin_client.application.app_context():
        material = db.session.get(RawMaterial, material_id)
        assert material.stock == Decimal("8.00")
        movement = StockMovement.query.filter_by(
            raw_material_id=material_id, reason="usage"
        ).one()
        assert movement.change_amount == Decimal("-2.00")
        assert movement.stock_after == Decimal("8.00")
        assert movement.notes == "Baked cakes"

    add_response = admin_client.post(
        f"/admin/raw-materials/{material_id}/stock",
        data={"action": "add", "quantity": "5"},
        follow_redirects=True,
    )
    assert add_response.status_code == 200
    with admin_client.application.app_context():
        material = db.session.get(RawMaterial, material_id)
        assert material.stock == Decimal("13.00")
        movement = StockMovement.query.filter_by(
            raw_material_id=material_id, reason="manual_restock"
        ).one()
        assert movement.change_amount == Decimal("5.00")


def test_insufficient_stock_usage_is_rejected(admin_client):
    create_admin_user(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Small Flour", stock=Decimal("1"))
        material_id = material.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/stock",
        data={"action": "usage", "quantity": "5"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Insufficient stock" in response.data
    with admin_client.application.app_context():
        assert db.session.get(RawMaterial, material_id).stock == Decimal("1.00")


def test_edit_details_saves_and_audits_without_touching_stock(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Edit Flour", stock=Decimal("7"), sku="OLD-SKU")
        material_id = material.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/details",
        data={
            "name": "Edit Flour Renamed",
            "sku": "NEW-SKU",
            "unit": "kg",
            "category": "Dairy",
            "reorder_level": "3",
            "min_stock": "1",
            "max_stock": "20",
            "preferred_supplier_id": "",
            "storage_location": "Chiller",
            "shelf_life_days": "10",
            "expiring_soon_days": "7",
            "notes": "Keep refrigerated",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with admin_client.application.app_context():
        material = db.session.get(RawMaterial, material_id)
        assert material.name == "Edit Flour Renamed"
        assert material.sku == "NEW-SKU"
        assert material.category == "Dairy"
        assert material.storage_location == "Chiller"
        assert material.shelf_life_days == 10
        assert material.stock == Decimal("7.00")
        audit = AuditLog.query.filter_by(
            entity_type="RawMaterial",
            entity_id=material_id,
            action="raw_material_details_updated",
        ).first()
        assert audit is not None
        assert material.updated_by is not None


def test_duplicate_name_edit_is_rejected(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        first = create_material(db.session, name="First Flour")
        second = create_material(db.session, name="Second Flour")
        first_id, second_id = first.id, second.id

    response = admin_client.post(
        f"/admin/raw-materials/{second_id}/details",
        data={"name": "First Flour", "unit": "kg"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Another material already uses that name" in response.data
    with admin_client.application.app_context():
        assert db.session.get(RawMaterial, second_id).name == "Second Flour"


def test_fefo_consumption_uses_earliest_expiry_batch_first(db_session, raw_material_factory):
    today = utcnow().date()
    material = raw_material_factory(name="FEFO Butter", stock=Decimal("10"))
    later = MaterialBatch(
        raw_material_id=material.id,
        batch_number="LATER",
        received_quantity=Decimal("5"),
        remaining_quantity=Decimal("5"),
        expiry_date=today + timedelta(days=30),
        received_at=utcnow(),
        status="available",
    )
    sooner = MaterialBatch(
        raw_material_id=material.id,
        batch_number="SOONER",
        received_quantity=Decimal("5"),
        remaining_quantity=Decimal("5"),
        expiry_date=today + timedelta(days=5),
        received_at=utcnow() - timedelta(days=1),
        status="available",
    )
    db_session.add_all([later, sooner])
    db_session.commit()

    get_container().inventory_service.record_usage(
        material, Decimal("3"), actor_id=None
    )
    db_session.commit()

    sooner = MaterialBatch.query.filter_by(batch_number="SOONER").one()
    later = MaterialBatch.query.filter_by(batch_number="LATER").one()
    assert sooner.remaining_quantity == Decimal("2.00")
    assert sooner.status == "partially_used"
    assert later.remaining_quantity == Decimal("5.00")


def test_expired_and_damaged_batches_excluded_from_usable_quantity(db_session, raw_material_factory):
    material = raw_material_factory(name="Expiry Flour", stock=Decimal("10"))
    expired = MaterialBatch(
        raw_material_id=material.id,
        batch_number="EXPIRED",
        received_quantity=Decimal("5"),
        remaining_quantity=Decimal("5"),
        expiry_date=utcnow().date() - timedelta(days=1),
        received_at=utcnow(),
        status="available",
    )
    damaged = MaterialBatch(
        raw_material_id=material.id,
        batch_number="DAMAGED",
        received_quantity=Decimal("5"),
        remaining_quantity=Decimal("5"),
        expiry_date=utcnow().date() + timedelta(days=30),
        received_at=utcnow(),
        status="damaged",
    )
    db_session.add_all([expired, damaged])
    db_session.commit()

    get_container().inventory_service.refresh_batch_statuses(material)
    db_session.commit()

    context = get_container().inventory_service.material_detail_context(material)
    expired_batch = next(b for b in context["batches"] if b.batch_number == "EXPIRED")
    assert expired_batch.status == "expired"
    damaged_batch = next(b for b in context["batches"] if b.batch_number == "DAMAGED")
    assert damaged_batch.usable_quantity == Decimal("0")
    assert context["expiry_summary"]["status"] in {"expired", "none"}


def test_multi_payment_partial_and_overpay_blocked(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Payment Flour", stock=Decimal("0"))
        vendor, po = create_received_po(
            db.session,
            material,
            quantity=Decimal("10"),
            unit_cost=Decimal("40"),
            payment_amount=Decimal("100"),
        )
        po_id = po.id
        vendor_id = vendor.id

    with admin_client.application.app_context():
        service = get_container().purchase_order_service
        payments = service.payments(db.session.get(PurchaseOrder, po_id))
        assert len(payments) == 1
        assert service.paid_amount(db.session.get(PurchaseOrder, po_id)) == Decimal("100.00")

    partial = admin_client.post(
        f"/admin/purchase-orders/{po_id}/payments",
        data={"payment_amount": "100", "payment_method": "UPI"},
        follow_redirects=True,
    )
    assert partial.status_code == 200
    with admin_client.application.app_context():
        service = get_container().purchase_order_service
        po = db.session.get(PurchaseOrder, po_id)
        assert service.paid_amount(po) == Decimal("200.00")
        assert service.remaining_amount(po) == Decimal("200.00")

    settle = admin_client.post(
        f"/admin/purchase-orders/{po_id}/payments",
        data={"payment_amount": "200", "payment_method": "CASH"},
        follow_redirects=True,
    )
    assert settle.status_code == 200
    with admin_client.application.app_context():
        service = get_container().purchase_order_service
        po = db.session.get(PurchaseOrder, po_id)
        assert service.remaining_amount(po) == Decimal("0.00")

    overpay = admin_client.post(
        f"/admin/purchase-orders/{po_id}/payments",
        data={"payment_amount": "500", "payment_method": "UPI"},
        follow_redirects=True,
    )
    assert overpay.status_code == 200
    assert b"exceeds the remaining amount" in overpay.data
    with admin_client.application.app_context():
        service = get_container().purchase_order_service
        po = db.session.get(PurchaseOrder, po_id)
        assert service.paid_amount(po) == Decimal("400.00")


def test_purchase_order_detail_shows_multiple_payments(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Detail Flour", stock=Decimal("0"))
        vendor, po = create_received_po(
            db.session,
            material,
            quantity=Decimal("4"),
            unit_cost=Decimal("25"),
            payment_amount=Decimal("25"),
        )
        po_id = po.id
    admin_client.post(
        f"/admin/purchase-orders/{po_id}/payments",
        data={"payment_amount": "25", "payment_method": "UPI"},
        follow_redirects=True,
    )

    response = admin_client.get(f"/admin/purchase-orders/{po_id}")
    assert response.status_code == 200
    assert b"Payments (2)" in response.data
    assert b"Record Payment" in response.data


def test_batch_status_change_updates_usable_quantity(admin_client):
    create_admin_user(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Block Flour", stock=Decimal("10"))
        batch = MaterialBatch(
            raw_material_id=material.id,
            batch_number="BLOCK",
            received_quantity=Decimal("5"),
            remaining_quantity=Decimal("5"),
            expiry_date=utcnow().date() + timedelta(days=30),
            received_at=utcnow(),
            status="available",
        )
        db.session.add(batch)
        db.session.commit()
        material_id = material.id
        batch_id = batch.id

    response = admin_client.post(
        f"/admin/raw-materials/{material_id}/batches/{batch_id}/status",
        data={"status": "blocked", "notes": "Quality hold"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with admin_client.application.app_context():
        batch = db.session.get(MaterialBatch, batch_id)
        assert batch.status == "blocked"
        assert batch.usable_quantity == Decimal("0")
        audit = AuditLog.query.filter_by(
            entity_type="MaterialBatch",
            entity_id=batch_id,
            action="material_batch_status_changed",
        ).first()
        assert audit is not None


def test_document_upload_and_download_requires_manager(admin_client):
    create_admin_user(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Doc Flour")
        material_id = material.id

    upload = admin_client.post(
        f"/admin/raw-materials/{material_id}/documents",
        data={
            "doc_type": "supplier_invoice",
            "document": (BytesIO(b"%PDF-1.4 fake pdf"), "invoice.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload.status_code == 200
    with admin_client.application.app_context():
        doc = MaterialDocument.query.filter_by(raw_material_id=material_id).one()
        assert doc.doc_type == "supplier_invoice"
        assert doc.original_filename == "invoice.pdf"
        document_id = doc.id

    download = admin_client.get(f"/admin/raw-materials/documents/{document_id}/file")
    assert download.status_code == 200
    assert b"%PDF-1.4" in download.data


def test_document_upload_blocked_for_staff(admin_client):
    create_admin_user(admin_client.application, "staff@bakery.com", "staff")
    sign_in(admin_client, "staff@bakery.com", "AdminTier1")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Staff Doc Flour")
        material_id = material.id

    upload = admin_client.post(
        f"/admin/raw-materials/{material_id}/documents",
        data={
            "doc_type": "supplier_invoice",
            "document": (BytesIO(b"%PDF-1.4 fake pdf"), "invoice.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert upload.status_code == 403


def test_receive_purchase_order_with_partial_payment_and_batch(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        material = create_material(db.session, name="Partial Flour", stock=Decimal("0"))
        vendor = Vendor(
            name="Partial Vendor",
            contact_person="C",
            phone="9999990001",
            is_active=True,
        )
        db.session.add(vendor)
        db.session.flush()
        po = PurchaseOrder(
            vendor_id=vendor.id,
            status="ordered",
            order_date=utcnow().date(),
            gst_rate_percent=Decimal("0"),
        )
        db.session.add(po)
        db.session.flush()
        item = PurchaseOrderItem(
            purchase_order_id=po.id,
            raw_material_id=material.id,
            quantity=Decimal("10"),
            unit_cost=Decimal("40"),
        )
        db.session.add(item)
        db.session.commit()
        po_id = po.id
        material_id = material.id

    receive = admin_client.post(
        f"/admin/purchase-orders/{po_id}/status",
        data={
            "action": "received",
            "payment_method": "UPI",
            "payment_amount": "150",
            f"batch_{po_id}_batch_number": "FL-001",
            f"batch_{po_id}_expiry_date": "2026-12-01",
            f"batch_{po_id}_storage_location": "Chiller",
        },
        follow_redirects=True,
    )
    assert receive.status_code == 200
    with admin_client.application.app_context():
        material = db.session.get(RawMaterial, material_id)
        assert material.stock == Decimal("10.00")
        assert material.last_purchased_at is not None
        assert material.last_purchase_quantity == Decimal("10.00")
        batch = MaterialBatch.query.filter_by(
            raw_material_id=material_id, batch_number="FL-001"
        ).one()
        assert batch.remaining_quantity == Decimal("10.00")
        assert str(batch.expiry_date) == "2026-12-01"
        service = get_container().purchase_order_service
        po = db.session.get(PurchaseOrder, po_id)
        assert service.paid_amount(po) == Decimal("150.00")
        assert service.remaining_amount(po) == Decimal("250.00")
