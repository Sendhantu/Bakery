from datetime import timedelta
from decimal import Decimal

import pytest

from clock import utcnow
from exceptions import ValidationError
from models import (
    AuditLog,
    Cart,
    CustomerRestriction,
    CustomerRiskAction,
    FraudBlocklistEntry,
    FraudAlert,
    Order,
    Product,
    ProductVariant,
    User,
    db,
)
from services.customer_risk_service import NEUTRAL_MESSAGE


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _customer(app):
    return User.query.filter_by(email="customer@test.com").first()


def _admin(app):
    return User.query.filter_by(email="admin@bakery.com").first()


def _service(app):
    return app.extensions["service_container"].customer_risk_service


def create_cart_item(app, *, customer_id, price="120"):
    with app.app_context():
        product = Product(
            name=f"Risk Test Cake {customer_id}",
            base_price=Decimal(price),
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Standard",
            price=Decimal(price),
            stock=5,
        )
        db.session.add(variant)
        db.session.flush()
        db.session.add(
            Cart(
                user_id=customer_id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()
        return product.id


def checkout_payload():
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    return {
        "fulfillment_type": "PICKUP",
        "pickup_date": tomorrow,
        "pickup_slot": "09:00 - 11:00",
        "pickup_phone": "9999999999",
        "payment_method": "COD",
        "occasion": "Birthday",
        "special_note": "Pickup at the front counter",
    }


def create_admin(app, email, tier):
    with app.app_context():
        user = User(
            name=f"{tier.title()} Admin",
            email=email,
            role="admin",
            admin_tier=tier,
            is_active=True,
        )
        user.set_password("AdminTier1")
        db.session.add(user)
        db.session.commit()
        return user.id


# ── Service-level workflow ─────────────────────────────────────


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_flag_creates_profile_restricts_and_records_action(app_ctx):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    profile = service.flag(
        customer,
        actor_id=admin.id,
        reason_category="repeated_fake_orders",
        reason="Customer placed several fake orders.",
    )
    db.session.commit()

    assert profile.risk_status == "flagged"
    assert profile.account_status == "restricted"
    assert customer.is_active is True
    action = CustomerRiskAction.query.filter_by(
        user_id=customer.id, action_type="flagged"
    ).first()
    assert action is not None
    assert action.reason_category == "repeated_fake_orders"


def test_flag_never_deletes_or_deactivates(app_ctx):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    service.flag(
        customer,
        actor_id=admin.id,
        reason_category="other",
        reason="Manual flag test.",
    )
    db.session.commit()

    customer = User.query.filter_by(email="customer@test.com").first()
    assert customer is not None
    assert customer.is_active is True


def test_suspension_blocks_login_and_purchase(app_ctx):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    service.suspend(
        customer,
        actor_id=admin.id,
        reason="Repeated payment failures.",
    )
    db.session.commit()

    service = _service(app)
    customer = User.query.filter_by(email="customer@test.com").first()
    assert service.login_blocked_message(customer) == NEUTRAL_MESSAGE
    assert service.purchase_error(customer) == NEUTRAL_MESSAGE
    assert service.ai_error(customer) == NEUTRAL_MESSAGE


def test_suspended_customer_cannot_log_in(client):
    app = client.application
    with app.app_context():
        customer = _customer(app)
        service = _service(app)
        admin = _admin(app)
        service.suspend(
            customer,
            actor_id=admin.id,
            reason="Test suspension.",
        )
        db.session.commit()

    response = sign_in(client, "customer@test.com", "customer123")
    assert response.status_code == 200
    assert b"temporarily unavailable" in response.data


def test_block_purchases_restriction_enforced_at_checkout(client):
    app = client.application
    with app.app_context():
        customer = _customer(app)
        service = _service(app)
        admin = _admin(app)
        create_cart_item(app, customer_id=customer.id)
        service.add_restriction(
            customer,
            restriction_type="block_purchases",
            reason="Suspected abuse.",
            duration_days=7,
            actor_id=admin.id,
        )
        db.session.commit()

    sign_in(client, "customer@test.com", "customer123")
    response = client.post(
        "/checkout", data=checkout_payload(), follow_redirects=False
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("temporarily unavailable" in text for _, text in flashes)
    with app.app_context():
        assert Order.query.count() == 0


def test_cod_restriction_forces_prepaid(client):
    app = client.application
    with app.app_context():
        customer = _customer(app)
        service = _service(app)
        admin = _admin(app)
        create_cart_item(app, customer_id=customer.id)
        service.add_restriction(
            customer,
            restriction_type="block_cod",
            reason="Previous COD refusal.",
            actor_id=admin.id,
        )
        db.session.commit()

    sign_in(client, "customer@test.com", "customer123")
    response = client.post(
        "/checkout", data=checkout_payload(), follow_redirects=False
    )
    assert response.status_code == 302
    with app.app_context():
        assert Order.query.count() == 0


def test_manual_approval_puts_order_on_hold(client):
    app = client.application
    with app.app_context():
        customer = _customer(app)
        service = _service(app)
        admin = _admin(app)
        create_cart_item(app, customer_id=customer.id)
        service.add_restriction(
            customer,
            restriction_type="require_manual_approval",
            reason="Case under review.",
            actor_id=admin.id,
        )
        db.session.commit()

    sign_in(client, "customer@test.com", "customer123")
    response = client.post(
        "/checkout", data=checkout_payload(), follow_redirects=True
    )
    assert response.status_code == 200
    with app.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        assert order is not None
        assert order.status == "ON_HOLD"
        alert = FraudAlert.query.filter_by(order_id=order.id).first()
        assert alert is not None
        assert alert.alert_type == "requires_manual_approval"


def test_soft_delete_and_restore(app_ctx):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    service.add_restriction(
        customer,
        restriction_type="block_purchases",
        reason="Temporary.",
        duration_days=3,
        actor_id=admin.id,
    )
    service.soft_delete(
        customer,
        actor_id=admin.id,
        reason="Customer requested deletion.",
        confirm="DELETE CUSTOMER",
    )
    db.session.commit()

    db.session.expire_all()
    customer = User.query.filter_by(email="customer@test.com").first()
    assert customer.is_active is False
    assert _service(app).login_blocked_message(customer) == NEUTRAL_MESSAGE

    _service(app).restore(
        customer,
        actor_id=admin.id,
        reason="Customer asked to reactivate.",
    )
    db.session.commit()

    db.session.expire_all()
    customer = User.query.filter_by(email="customer@test.com").first()
    assert customer.is_active is True
    assert _service(app).login_blocked_message(customer) is None
    assert _service(app).active_restrictions(customer) == []


def test_soft_delete_requires_confirmation(app_ctx):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    with pytest.raises(ValidationError):
        service.soft_delete(
            customer,
            actor_id=admin.id,
            reason="Requested deletion.",
            confirm="DELETE",
        )
    assert _customer(app).is_active is True


def test_permanent_delete_blocked_by_financial_records(app_ctx, db_session, order_factory):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)
    order_factory(customer=customer, status="PLACED", payment_status="PENDING")

    service.soft_delete(
        customer,
        actor_id=admin.id,
        reason="Requested deletion.",
        confirm="DELETE CUSTOMER",
    )
    db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        service.delete_permanently(
            customer,
            actor_id=admin.id,
            reason="Requested deletion.",
            confirm="DELETE CUSTOMER",
        )
    db_session.rollback()
    assert "active order(s)" in str(exc_info.value.args[0])


def test_anonymization_clears_personal_data(app_ctx, db_session, user_factory):
    app = app_ctx
    service = _service(app)
    admin = _admin(app)
    customer = user_factory(
        email="anon@example.com",
        name="Real Name",
    )
    customer.phone = "9876543210"
    db_session.commit()
    original_email = customer.email

    service.anonymize(
        customer,
        actor_id=admin.id,
        reason="Right to be forgotten.",
    )
    db_session.commit()

    db_session.expire_all()
    user = User.query.filter_by(id=customer.id).first()
    assert user.email != original_email
    assert user.email.endswith("@anonymized.invalid")
    assert user.phone is None
    assert user.name == "Deleted Customer"
    assert user.is_active is False
    profile = service.get_profile(user, create=False)
    assert profile.account_status == "anonymized"


def test_blocklist_add_flags_and_restricts_matching_customer(app_ctx, db_session):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    entry = service.add_blocklist(
        identifier_type="mobile_hash",
        identifier_value="+91 77777 77777",
        reason="Confirmed payment fraud.",
        actor_id=admin.id,
    )
    db_session.commit()

    assert entry.status == "pending_review"
    assert entry.match_count == 1
    customer = User.query.filter_by(email="customer@test.com").first()
    profile = service.get_profile(customer, create=False)
    assert profile.risk_status == "flagged"
    assert service.has_active_restriction(customer, "block_purchases")
    restriction = CustomerRestriction.query.filter_by(
        user_id=customer.id, restriction_type="block_purchases", is_active=True
    ).first()
    assert restriction is not None
    assert restriction.is_temporary


def test_blocklist_review_by_manager(app_ctx, db_session):
    app = app_ctx
    service = _service(app)
    admin = _admin(app)
    entry = service.add_blocklist(
        identifier_type="email_hash",
        identifier_value="customer@test.com",
        reason="Linked to chargeback abuse.",
        actor_id=admin.id,
    )
    db_session.commit()

    service.review_blocklist(
        entry.id,
        status="approved",
        review_notes="Evidence confirmed.",
        actor_id=admin.id,
    )
    db_session.commit()

    entry = db.session.get(FraudBlocklistEntry, entry.id)
    assert entry.status == "approved"
    assert entry.review_notes == "Evidence confirmed."


def test_audit_log_records_risk_action(app_ctx, db_session):
    app = app_ctx
    customer = _customer(app)
    service = _service(app)
    admin = _admin(app)

    service.flag(
        customer,
        actor_id=admin.id,
        reason_category="payment_fraud",
        reason="Chargeback received.",
    )
    db_session.commit()

    audit = AuditLog.query.filter_by(
        actor_id=admin.id,
        action="flagged",
        entity_type="CustomerRiskProfile",
    ).first()
    assert audit is not None
    assert audit.entity_id == str(customer.id)


# ── Admin portal gating ────────────────────────────────────────


def test_owner_can_access_customer_detail_with_risk_context(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.get("/admin/customers")
    assert response.status_code == 200

    with admin_client.application.app_context():
        customer = _customer(admin_client.application)
    detail = admin_client.get(f"/admin/customers/{customer.id}")
    assert detail.status_code == 200
    assert b"Risk" in detail.data


def test_staff_can_flag_but_not_anonymize(admin_client):
    create_admin(admin_client.application, "staff@bakery.com", "staff")
    sign_in(admin_client, "staff@bakery.com", "AdminTier1")

    with admin_client.application.app_context():
        customer = _customer(admin_client.application)
    response = admin_client.post(
        f"/admin/customers/{customer.id}/risk/flag",
        data={
            "reason_category": "gift_card_abuse",
            "reason": "Multiple gift cards charged back.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with admin_client.application.app_context():
        profile = _service(admin_client.application).get_profile(
            customer, create=False
        )
        assert profile.risk_status == "flagged"

    deny = admin_client.post(
        f"/admin/customers/{customer.id}/risk/anonymize",
        data={"reason": "Not allowed."},
    )
    assert deny.status_code == 403


def test_cashier_has_no_customer_section(admin_client):
    create_admin(admin_client.application, "cashier@bakery.com", "cashier")
    sign_in(admin_client, "cashier@bakery.com", "AdminTier1")

    response = admin_client.get("/admin/customers")
    assert response.status_code == 403


def test_manager_can_block_and_soft_delete(admin_client):
    create_admin(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")

    with admin_client.application.app_context():
        customer = _customer(admin_client.application)
    block = admin_client.post(
        f"/admin/customers/{customer.id}/risk/block",
        data={"reason": "Confirmed fraudulent activity."},
        follow_redirects=False,
    )
    assert block.status_code == 302
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        profile = _service(admin_client.application).get_profile(
            customer, create=False
        )
        assert profile.account_status == "blocked"

    soft_delete = admin_client.post(
        f"/admin/customers/{customer.id}/risk/soft-delete",
        data={
            "reason": "Case concluded; deletion requested.",
            "confirm": "DELETE CUSTOMER",
        },
        follow_redirects=False,
    )
    assert soft_delete.status_code == 302
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        profile = _service(admin_client.application).get_profile(
            customer, create=False
        )
        assert profile.account_status == "soft_deleted"


def test_owner_can_anonymize(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    with admin_client.application.app_context():
        customer_id = _customer(admin_client.application).id
    response = admin_client.post(
        f"/admin/customers/{customer_id}/risk/anonymize",
        data={"reason": "Right to be forgotten."},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with admin_client.application.app_context():
        customer = User.query.filter_by(id=customer_id).first()
        profile = _service(admin_client.application).get_profile(
            customer, create=False
        )
        assert profile.account_status == "anonymized"
        assert customer.email.endswith("@anonymized.invalid")


def test_manager_cannot_permanently_delete(admin_client):
    create_admin(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")

    with admin_client.application.app_context():
        customer = _customer(admin_client.application)
    response = admin_client.post(
        f"/admin/customers/{customer.id}/risk/delete",
        data={
            "reason": "Purge record.",
            "confirm": "DELETE CUSTOMER",
        },
    )
    assert response.status_code == 403
