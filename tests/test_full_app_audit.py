import json
from decimal import Decimal

import pytest

from clock import utcnow
from models import Delivery, DeliveryAgent, Order, RawMaterial, User, db, socketio
from services.triage_service import generate_smart_triage_report, summarize_triage_report


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Missing CSRF tokens are rejected, but the catch-all error handler re-raises "
        "CSRFError/HTTPException instead of returning the expected 400 response."
    ),
)
def test_admin_post_routes_enforce_csrf_when_enabled(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    old_csrf_value = admin_client.application.config.get("WTF_CSRF_ENABLED")
    old_propagate_value = admin_client.application.config.get("PROPAGATE_EXCEPTIONS")
    admin_client.application.config["WTF_CSRF_ENABLED"] = True
    admin_client.application.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        response = admin_client.post(
            "/admin/vendors/add",
            data={"name": "CSRF Vendor", "email": "vendor@example.test"},
            follow_redirects=False,
        )
    finally:
        admin_client.application.config["WTF_CSRF_ENABLED"] = old_csrf_value
        admin_client.application.config["PROPAGATE_EXCEPTIONS"] = old_propagate_value

    assert response.status_code == 400


def test_customer_cannot_view_or_cancel_another_customers_order(
    client,
    user_factory,
    order_factory,
):
    owner = user_factory(
        email="audit.owner@example.test",
        password="CustomerPass1",
        role="customer",
        name="Order Owner",
    )
    other_customer = user_factory(
        email="audit.other@example.test",
        password="CustomerPass1",
        role="customer",
        name="Other Customer",
    )
    order = order_factory(customer=owner, status="PLACED", payment_status="PENDING")
    db.session.commit()

    sign_in(client, other_customer.email, "CustomerPass1")

    detail_response = client.get(f"/orders/{order.id}", follow_redirects=False)
    cancel_response = client.post(
        f"/orders/{order.id}/cancel",
        data={"reason": "Trying another customer's order"},
        follow_redirects=False,
    )

    assert detail_response.status_code == 404
    assert cancel_response.status_code == 404


def test_delivery_agent_cannot_view_or_update_another_agents_assignment(
    delivery_client,
    user_factory,
    order_factory,
):
    assigned_user = user_factory(
        email="audit.assigned.driver@example.test",
        password="DeliveryPass1",
        role="delivery",
        name="Assigned Driver",
    )
    assigned_agent = DeliveryAgent(
        user_id=assigned_user.id,
        name="Assigned Driver",
        phone="9000011111",
        availability=True,
    )
    db.session.add(assigned_agent)
    db.session.flush()
    order = order_factory(status="OUT_FOR_DELIVERY", payment_status="PAID")
    db.session.add(
        Delivery(
            order_id=order.id,
            agent_id=assigned_agent.id,
            assigned_time=utcnow(),
            status="OUT_FOR_DELIVERY",
        )
    )
    db.session.commit()

    sign_in(delivery_client, "delivery@bakery.com", "delivery123")

    detail_response = delivery_client.get(
        f"/delivery/order/{order.id}",
        follow_redirects=False,
    )
    update_response = delivery_client.post(
        f"/delivery/order/{order.id}/update",
        data={"status": "DELIVERED"},
        follow_redirects=False,
    )

    assert detail_response.status_code == 404
    assert update_response.status_code == 404


def test_staff_tier_is_blocked_from_sensitive_adjustment_surfaces(
    admin_client,
):
    with admin_client.application.app_context():
        user = User(
            name="Audit Staff",
            email="audit.staff@example.test",
            role="admin",
            admin_tier="staff",
            is_active=True,
        )
        user.set_password("AdminTier1")
        db.session.add(user)
        db.session.commit()

    sign_in(admin_client, "audit.staff@example.test", "AdminTier1")

    responses = [
        admin_client.get("/admin/finance", follow_redirects=False),
        admin_client.get("/admin/audit-log", follow_redirects=False),
        admin_client.get("/admin/staff", follow_redirects=False),
        admin_client.post(
            "/admin/gift-cards/issue",
            data={"amount": "100", "recipient_email": "guest@example.test"},
            follow_redirects=False,
        ),
        admin_client.post(
            "/admin/loyalty/adjust",
            data={"user_id": 1, "points": 10, "reason": "audit probe"},
            follow_redirects=False,
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403]


def test_pos_sale_commits_even_when_socket_emit_fails(
    admin_client,
    raw_material_factory,
    product_factory,
    monkeypatch,
):
    flour = raw_material_factory(name="Audit Socket Flour", stock=Decimal("5"))
    _product, variant = product_factory(
        name="Audit Socket Cake",
        price=Decimal("50"),
        variant_stock=3,
        recipe=[(flour, Decimal("1"))],
    )
    db.session.commit()

    def fail_emit(*args, **kwargs):
        raise RuntimeError("socket unavailable during audit test")

    monkeypatch.setattr(socketio, "emit", fail_emit)
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 1}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "CASH",
            "sale_status": "DELIVERED",
            "customer_name": "Audit Walk-in",
            "customer_phone": "9000090000",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with admin_client.application.app_context():
        order = (
            Order.query.filter_by(channel="counter", source="POS")
            .order_by(Order.id.desc())
            .first()
        )
        assert order is not None
        assert order.payment_status == "PENDING"
        assert Decimal(str(order.total)) == Decimal("52.50")


def test_triage_ai_fallback_is_deterministic_and_does_not_invent_stock(
    raw_material_factory,
    product_factory,
    order_factory,
):
    flour = raw_material_factory(
        name="Audit Triage Flour",
        stock=Decimal("0.25"),
        reorder_level=Decimal("1"),
        unit="kg",
    )
    product, variant = product_factory(
        name="Audit Triage Bread",
        price=Decimal("40"),
        variant_stock=5,
        recipe=[(flour, Decimal("1"))],
    )
    order = order_factory(
        product=product,
        variant=variant,
        quantity=1,
        total=Decimal("40"),
        status="PLACED",
    )
    db.session.commit()

    report = generate_smart_triage_report([order])
    summary = summarize_triage_report(report)

    note = summary["notes"][order.id]
    assert summary["llm_available"] is False
    assert "Audit Triage Flour" in note
    assert "short by 0.75 kg" in note
