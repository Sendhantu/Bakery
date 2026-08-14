from datetime import timedelta
from decimal import Decimal

from clock import utcnow
from models import (
    Branch,
    DeliveryAgent,
    DeliveryCashLedger,
    Order,
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


def create_admin_user(name, email, role, branch, password="RolePass1"):
    user = User(
        name=name,
        email=email,
        role=role,
        admin_tier="manager" if role == "branch_manager" else "staff",
        branch_id=branch.id if branch else None,
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def create_branch_order(customer, branch, label):
    order = Order(
        order_number=Order.generate_order_number(),
        user_id=customer.id,
        branch_id=branch.id,
        status="PLACED",
        subtotal=Decimal("100"),
        total=Decimal("100"),
        payment_method="CASH",
        payment_status="PENDING",
        fulfillment_type="PICKUP",
        delivery_slot="Walk-in",
        delivery_date=utcnow().date() + timedelta(days=1),
        special_note=label,
    )
    db.session.add(order)
    db.session.flush()
    return order


def branch_access_fixture():
    customer = User.query.filter_by(email="customer@test.com").first()
    branch_a = Branch(name="RBAC Branch A", phone="9000000101")
    branch_b = Branch(name="RBAC Branch B", phone="9000000102")
    db.session.add_all([branch_a, branch_b])
    db.session.flush()
    create_admin_user(
        "Branch A Manager",
        "branch.a.manager@test.com",
        "branch_manager",
        branch_a,
    )
    create_admin_user(
        "Branch A Cashier",
        "branch.a.cashier@test.com",
        "cashier",
        branch_a,
    )
    create_admin_user(
        "Branch B Cashier",
        "branch.b.cashier@test.com",
        "cashier",
        branch_b,
    )
    own_order = create_branch_order(customer, branch_a, "Visible branch order")
    other_order = create_branch_order(customer, branch_b, "Hidden branch order")
    product = Product(name="RBAC Product", base_price=Decimal("50"), is_active=True)
    db.session.add(product)
    db.session.flush()
    own_variant = ProductVariant(
        product_id=product.id,
        branch_id=branch_a.id,
        name="Branch A Pack",
        price=Decimal("50"),
        stock=5,
    )
    other_variant = ProductVariant(
        product_id=product.id,
        branch_id=branch_b.id,
        name="Branch B Pack",
        price=Decimal("50"),
        stock=5,
    )
    own_material = RawMaterial(
        name="RBAC Branch A Flour",
        branch_id=branch_a.id,
        unit="kg",
        stock=Decimal("5"),
        reorder_level=Decimal("1"),
    )
    other_material = RawMaterial(
        name="RBAC Branch B Flour",
        branch_id=branch_b.id,
        unit="kg",
        stock=Decimal("5"),
        reorder_level=Decimal("1"),
    )
    own_agent = DeliveryAgent(name="RBAC Branch A Rider", branch_id=branch_a.id)
    other_agent = DeliveryAgent(name="RBAC Branch B Rider", branch_id=branch_b.id)
    db.session.add_all(
        [own_variant, other_variant, own_material, other_material, own_agent, other_agent]
    )
    db.session.flush()
    db.session.add_all(
        [
            DeliveryCashLedger(
                agent_id=own_agent.id,
                action="cod_collected",
                amount=Decimal("100"),
                balance_after=Decimal("100"),
            ),
            DeliveryCashLedger(
                agent_id=other_agent.id,
                action="cod_collected",
                amount=Decimal("200"),
                balance_after=Decimal("200"),
            ),
        ]
    )
    db.session.commit()
    return {
        "branch_a": branch_a,
        "branch_b": branch_b,
        "own_order": own_order,
        "other_order": other_order,
        "own_variant": own_variant,
        "other_variant": other_variant,
        "own_material": own_material,
        "other_material": other_material,
        "own_agent": own_agent,
        "other_agent": other_agent,
    }


def test_branch_manager_order_access_is_limited_to_assigned_branch(admin_client):
    with admin_client.application.app_context():
        data = branch_access_fixture()
        own_order_id = data["own_order"].id
        other_order_id = data["other_order"].id
        own_order_number = data["own_order"].order_number.encode()
        other_order_number = data["other_order"].order_number.encode()

    sign_in(admin_client, "branch.a.manager@test.com", "RolePass1")

    list_response = admin_client.get("/admin/orders")
    assert list_response.status_code == 200
    assert own_order_number in list_response.data
    assert other_order_number not in list_response.data

    assert admin_client.get(f"/admin/orders/{own_order_id}").status_code == 200
    assert admin_client.get(f"/admin/orders/{other_order_id}").status_code == 403

    update_response = admin_client.post(
        f"/admin/orders/{other_order_id}/update-status",
        data={"status": "PREPARING"},
    )
    assert update_response.status_code == 403


def test_branch_cashier_pos_payment_and_receipt_are_branch_scoped(admin_client):
    with admin_client.application.app_context():
        data = branch_access_fixture()
        own_order = data["own_order"]
        other_order = data["other_order"]
        own_order.channel = "counter"
        other_order.channel = "counter"
        db.session.commit()
        own_order_id = own_order.id
        other_order_id = other_order.id

    sign_in(admin_client, "branch.a.cashier@test.com", "RolePass1")

    own_payment = admin_client.get(f"/admin/pos/orders/{own_order_id}/payment")
    assert own_payment.status_code == 200
    assert b"Collect Walk-in Payment" in own_payment.data

    assert admin_client.get(f"/admin/pos/orders/{other_order_id}/payment").status_code == 403
    assert admin_client.get(f"/admin/pos/orders/{other_order_id}/receipt").status_code == 403


def test_branch_inventory_and_delivery_cash_are_scoped(admin_client):
    with admin_client.application.app_context():
        data = branch_access_fixture()
        own_variant_id = data["own_variant"].id
        other_variant_id = data["other_variant"].id
        own_material_id = data["own_material"].id
        other_material_id = data["other_material"].id
        own_agent_id = data["own_agent"].id
        other_agent_id = data["other_agent"].id

    sign_in(admin_client, "branch.a.manager@test.com", "RolePass1")

    inventory_response = admin_client.get("/admin/inventory")
    assert inventory_response.status_code == 200
    material_inventory_response = admin_client.get("/admin/inventory?view=materials")
    assert material_inventory_response.status_code == 200
    assert b"RBAC Branch A Flour" in material_inventory_response.data
    assert b"RBAC Branch B Flour" not in material_inventory_response.data

    own_stock_update = admin_client.post(
        "/admin/inventory/update",
        data={"variant_id": own_variant_id, "stock": "7"},
        follow_redirects=False,
    )
    assert own_stock_update.status_code == 302

    assert (
        admin_client.post(
            "/admin/inventory/update",
            data={"variant_id": other_variant_id, "stock": "8"},
        ).status_code
        == 403
    )
    assert (
        admin_client.post(
            "/admin/inventory/raw-material/update",
            data={"material_id": other_material_id, "stock": "8"},
        ).status_code
        == 403
    )

    own_raw_update = admin_client.post(
        "/admin/inventory/raw-material/update",
        data={"material_id": own_material_id, "stock": "6"},
        follow_redirects=False,
    )
    assert own_raw_update.status_code in {302, 303}

    delivery_cash = admin_client.get("/admin/delivery-cash")
    assert delivery_cash.status_code == 200
    assert b"RBAC Branch A Rider" in delivery_cash.data
    assert b"RBAC Branch B Rider" not in delivery_cash.data

    assert admin_client.get(f"/admin/delivery-cash?agent_id={own_agent_id}").status_code == 200
    assert admin_client.get(f"/admin/delivery-cash?agent_id={other_agent_id}").status_code == 403
    assert (
        admin_client.post(
            f"/admin/delivery-cash/{other_agent_id}/handover",
            data={"amount": "100"},
        ).status_code
        == 403
    )
