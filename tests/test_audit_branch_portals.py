from decimal import Decimal
from io import BytesIO

from models import (
    AuditDocument,
    AuditLog,
    AuditReportDownload,
    AuditorRequirement,
    Branch,
    Category,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    RawMaterial,
    User,
    db,
)


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_branch_user(app, *, branch_id, email, role="branch_manager", password="Branch123"):
    with app.app_context():
        user = User(
            name=email.split("@")[0].replace(".", " ").title(),
            email=email,
            role=role,
            admin_tier="manager" if role == "branch_manager" else "staff",
            branch_id=branch_id,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def test_auditor_can_access_audit_portal_but_not_write_or_enter_other_portals(app_factory):
    audit_app = app_factory("audit")
    audit_client = audit_app.test_client()

    response = sign_in(audit_client, "auditor@bakery.com", "Auditor123")
    assert response.status_code == 302
    assert "/audit/" in response.headers["Location"]

    dashboard = audit_client.get("/audit/")
    assert dashboard.status_code == 200
    assert b"Auditor Portal" in dashboard.data

    assert audit_client.post("/audit/").status_code == 403
    assert audit_client.get("/admin/").status_code == 403
    assert audit_client.get("/branch/").status_code == 403


def test_expanded_auditor_portal_pages_are_read_only_and_render_financial_reviews(app_factory):
    audit_app = app_factory("audit")
    audit_client = audit_app.test_client()
    with audit_app.app_context():
        branch = Branch.query.filter_by(name="Anna Nagar").first()
        customer = User.query.filter_by(email="customer@test.com").first()
        category = Category.query.first() or Category(name="Audit Cake", icon="cake")
        db.session.add(category)
        db.session.flush()
        product = Product(
            name="Audit Review Cake",
            base_price=Decimal("200"),
            category_id=category.id,
            is_active=True,
        )
        variant = ProductVariant(
            product=product,
            branch_id=branch.id if branch else None,
            name="Slice",
            price=Decimal("200"),
            stock=5,
        )
        db.session.add_all([product, variant])
        db.session.flush()
        order = Order(
            order_number=Order.generate_order_number(),
            invoice_number="AUD-INV-001",
            user_id=customer.id,
            branch_id=branch.id if branch else None,
            status="DELIVERED",
            subtotal=Decimal("200"),
            gst_taxable_amount=Decimal("200"),
            gst_amount=Decimal("10"),
            total=Decimal("210"),
            payment_method="UPI",
            payment_status="PAID",
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                variant_id=variant.id,
                product_name=product.name,
                variant_name=variant.name,
                quantity=1,
                unit_price=Decimal("200"),
                subtotal=Decimal("200"),
            )
        )
        db.session.commit()
        order_id = order.id
        branch_id = branch.id if branch else None

    sign_in(audit_client, "auditor@bakery.com", "Auditor123")

    paths = [
        "/audit/",
        "/audit/sales",
        f"/audit/sales/{order_id}",
        "/audit/revenue",
        "/audit/purchases",
        "/audit/expenses",
        "/audit/financial-statements",
        "/audit/financial-statements/profit-loss",
        "/audit/financial-statements/balance-sheet",
        "/audit/financial-statements/trial-balance",
        "/audit/financial-statements/general-ledger",
        "/audit/gst",
        "/audit/bank-cash",
        "/audit/receivables",
        "/audit/payables",
        "/audit/inventory",
        "/audit/fixed-assets",
        "/audit/payroll",
        "/audit/branches",
        "/audit/documents",
        "/audit/reports",
    ]
    if branch_id:
        paths.append(f"/audit/revenue/branches/{branch_id}")

    for path in paths:
        response = audit_client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        assert b"Read-only" in response.data

    sales = audit_client.get("/audit/sales?q=AUD-INV-001")
    assert sales.status_code == 200
    assert b"AUD-INV-001" in sales.data
    assert b"Audit Review Cake" not in sales.data

    detail = audit_client.get(f"/audit/sales/{order_id}")
    assert detail.status_code == 200
    assert b"Audit Review Cake" in detail.data
    assert b"Approve" not in detail.data
    assert b"Delete" not in detail.data

    assert audit_client.post("/audit/expenses").status_code == 403


def test_audit_report_downloads_are_generated_and_logged(app_factory):
    audit_app = app_factory("audit")
    audit_client = audit_app.test_client()
    sign_in(audit_client, "auditor@bakery.com", "Auditor123")

    csv_response = audit_client.get("/audit/reports/sales-register.csv")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    assert b"Invoice,Date,Branch" in csv_response.data

    pdf_response = audit_client.get("/audit/reports/profit-and-loss.pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"

    with audit_app.app_context():
        downloads = AuditReportDownload.query.order_by(AuditReportDownload.id).all()
        assert [download.report_key for download in downloads] == [
            "sales-register",
            "profit-and-loss",
        ]


def test_auditor_requirement_document_revision_workflow(app_factory, tmp_path):
    app = app_factory("admin")
    app.config["AUDIT_DOCUMENT_STORAGE_ROOT"] = str(tmp_path)
    client = app.test_client()

    sign_in(client, "auditor@bakery.com", "Auditor123")
    create_response = client.post(
        "/audit/requirements",
        data={
            "financial_year": "2026-27",
            "title": "April-June GST Challans",
            "category": "GST",
            "period_label": "April-June 2026",
            "priority": "HIGH",
            "due_date": "2026-08-31",
            "description": "Provide GST payment challans for April, May and June.",
        },
        follow_redirects=True,
    )
    assert create_response.status_code == 200

    with app.app_context():
        requirement = AuditorRequirement.query.filter_by(
            title="April-June GST Challans"
        ).first()
        assert requirement is not None
        requirement_id = requirement.id
        requirement_uid = requirement.requirement_uid

    client.get("/auth/logout")
    sign_in(client, "admin@bakery.com", "Admin@bakery")
    admin_list = client.get("/admin/audit-management?section=requirements&financial_year=2026-27")
    assert admin_list.status_code == 200
    assert requirement_uid.encode() in admin_list.data

    respond = client.post(
        f"/admin/audit-management/requirements/{requirement_id}/respond",
        data={"admin_response": "April and May challans are attached for review."},
        follow_redirects=True,
    )
    assert respond.status_code == 200
    assert b"April and May challans are attached" in respond.data

    upload = client.post(
        "/admin/audit-management/documents/upload",
        data={
            "requirement_id": str(requirement_id),
            "title": "GST April 2026 Challan",
            "category": "GST",
            "financial_year": "2026-27",
            "period_label": "April 2026",
            "visibility": "INTERNAL",
            "status": "DRAFT",
            "documents": (BytesIO(b"gst challan"), "gst_april_2026.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload.status_code == 200

    with app.app_context():
        document = AuditDocument.query.filter_by(title="GST April 2026 Challan").first()
        assert document is not None
        assert document.is_auditor_visible is False
        document_id = document.id
        document_uid = document.document_uid

    client.get("/auth/logout")
    sign_in(client, "auditor@bakery.com", "Auditor123")
    assert client.get(f"/audit/documents/{document_uid}/download").status_code == 404

    client.get("/auth/logout")
    sign_in(client, "admin@bakery.com", "Admin@bakery")
    publish = client.post(
        f"/admin/audit-management/documents/{document_id}/publish",
        follow_redirects=True,
    )
    assert publish.status_code == 200
    submit = client.post(
        f"/admin/audit-management/requirements/{requirement_id}/submit",
        follow_redirects=True,
    )
    assert submit.status_code == 200
    assert b"Submitted To Auditor" in submit.data

    with app.app_context():
        second_auditor = User(
            name="Second Auditor",
            email="second.auditor@example.test",
            role="auditor",
            is_active=True,
        )
        second_auditor.set_password("Auditor123")
        db.session.add(second_auditor)
        db.session.commit()

    client.get("/auth/logout")
    sign_in(client, "second.auditor@example.test", "Auditor123")
    other_docs = client.get("/audit/documents?financial_year=2026-27")
    assert other_docs.status_code == 200
    assert b"GST April 2026 Challan" not in other_docs.data
    assert client.get(f"/audit/documents/{document_uid}/download").status_code == 404

    client.get("/auth/logout")
    sign_in(client, "auditor@bakery.com", "Auditor123")
    detail = client.get(f"/audit/requirements/{requirement_id}")
    assert detail.status_code == 200
    assert b"April and May challans are attached" in detail.data
    assert b"GST April 2026 Challan" in detail.data
    download = client.get(f"/audit/documents/{document_uid}/download")
    assert download.status_code == 200
    assert download.data == b"gst challan"

    revision = client.post(
        f"/audit/requirements/{requirement_id}/revision",
        data={"comment": "June challan is missing. Please upload it."},
        follow_redirects=True,
    )
    assert revision.status_code == 200
    assert b"June challan is missing" in revision.data

    client.get("/auth/logout")
    sign_in(client, "admin@bakery.com", "Admin@bakery")
    admin_detail = client.get(f"/admin/audit-management/requirements/{requirement_id}")
    assert admin_detail.status_code == 200
    assert b"NEEDS REVISION" not in admin_detail.data
    assert b"Needs Revision" in admin_detail.data
    assert b"June challan is missing" in admin_detail.data

    resubmit_response = client.post(
        f"/admin/audit-management/requirements/{requirement_id}/respond",
        data={"admin_response": "June challan has now been added."},
        follow_redirects=True,
    )
    assert resubmit_response.status_code == 200
    client.post(
        f"/admin/audit-management/requirements/{requirement_id}/submit",
        follow_redirects=True,
    )

    client.get("/auth/logout")
    sign_in(client, "auditor@bakery.com", "Auditor123")
    resolved = client.post(
        f"/audit/requirements/{requirement_id}/resolve",
        follow_redirects=True,
    )
    assert resolved.status_code == 200
    assert b"Resolved" in resolved.data

    with app.app_context():
        requirement = db.session.get(AuditorRequirement, requirement_id)
        assert requirement.status == "RESOLVED"
        assert len(requirement.events) >= 6


def test_admin_audit_management_sections_render(app_factory):
    app = app_factory("admin")
    client = app.test_client()
    sign_in(client, "admin@bakery.com", "Admin@bakery")

    for section in [
        "overview",
        "requirements",
        "documents",
        "reports",
        "accounts",
        "activity",
    ]:
        response = client.get(f"/admin/audit-management?section={section}")
        assert response.status_code == 200, section
        assert b"Audit Management" in response.data


def test_branch_user_only_sees_own_branch_stock_and_orders(app_factory):
    branch_app = app_factory("branch")
    branch_client = branch_app.test_client()
    with branch_app.app_context():
        branch_a = Branch(name="Portal Branch A", phone="9000000101")
        branch_b = Branch(name="Portal Branch B", phone="9000000102")
        db.session.add_all([branch_a, branch_b])
        db.session.flush()
        category = Category(name="Branch Portal Category", icon="cake")
        product = Product(
            name="Branch Portal Brownie",
            base_price=Decimal("80"),
            category=category,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        own_variant = ProductVariant(
            product_id=product.id,
            branch_id=branch_a.id,
            name="Counter",
            price=Decimal("80"),
            stock=7,
        )
        other_variant = ProductVariant(
            product_id=product.id,
            branch_id=branch_b.id,
            name="Other Counter",
            price=Decimal("80"),
            stock=11,
        )
        own_material = RawMaterial(
            name="Branch A Coffee Beans",
            branch_id=branch_a.id,
            unit="kg",
            stock=Decimal("4"),
            reorder_level=Decimal("1"),
            is_active=True,
        )
        other_material = RawMaterial(
            name="Branch B Coffee Beans",
            branch_id=branch_b.id,
            unit="kg",
            stock=Decimal("9"),
            reorder_level=Decimal("1"),
            is_active=True,
        )
        customer = User.query.filter_by(email="customer@test.com").first()
        other_order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            branch_id=branch_b.id,
            status="PLACED",
            subtotal=Decimal("100"),
            total=Decimal("100"),
            payment_status="PENDING",
        )
        db.session.add_all([own_variant, other_variant, own_material, other_material, other_order])
        db.session.commit()
        branch_a_id = branch_a.id
        other_order_id = other_order.id

    create_branch_user(
        branch_app,
        branch_id=branch_a_id,
        email="branch.a.manager@example.com",
        role="branch_staff",
    )
    sign_in(branch_client, "branch.a.manager@example.com", "Branch123")

    dashboard = branch_client.get("/branch/")
    assert dashboard.status_code == 200
    assert b"Portal Branch A Branch Dashboard" in dashboard.data

    stock = branch_client.get("/branch/stock")
    assert stock.status_code == 200
    assert b"Branch A Coffee Beans" in stock.data
    assert b"Branch B Coffee Beans" not in stock.data
    assert b"Other Counter" not in stock.data

    assert branch_client.get(f"/branch/orders/{other_order_id}").status_code == 404
    assert branch_client.get("/admin/").status_code == 403
    assert branch_client.get("/audit/").status_code == 403


def test_admin_audit_management_and_portal_previews_log_actual_admin(app_factory):
    admin_app = app_factory("admin")
    admin_client = admin_app.test_client()
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    management = admin_client.get("/admin/audit-management")
    assert management.status_code == 200
    assert b"Audit Management" in management.data

    audit_preview = admin_client.get("/admin/portal-preview/audit", follow_redirects=True)
    assert audit_preview.status_code == 200
    assert b"Viewing Auditor Portal as Administrator" in audit_preview.data

    branch_preview = admin_client.get("/admin/portal-preview/branch", follow_redirects=True)
    assert branch_preview.status_code == 200
    assert b"Branch Portal as Administrator" in branch_preview.data

    with admin_app.app_context():
        admin = User.query.filter_by(email="admin@bakery.com").first()
        preview_logs = AuditLog.query.filter_by(
            actor_id=admin.id,
            action="portal_preview_started",
            entity_type="Portal",
        ).all()
        assert len(preview_logs) >= 2
