from models import AuditLog, User, db


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


def test_seeded_admin_is_owner_and_can_access_finance_and_staff(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    finance_response = admin_client.get("/admin/finance")
    staff_response = admin_client.get("/admin/staff")

    assert finance_response.status_code == 200
    assert staff_response.status_code == 200
    with admin_client.application.app_context():
        admin = User.query.filter_by(email="admin@bakery.com").first()
        assert admin.role == "admin"
        assert admin.effective_admin_tier == "owner"


def test_manager_can_access_orders_but_finance_is_forbidden_and_logged(admin_client):
    create_admin_user(admin_client.application, "manager@bakery.com", "manager")
    sign_in(admin_client, "manager@bakery.com", "AdminTier1")

    orders_response = admin_client.get("/admin/orders")
    finance_response = admin_client.get("/admin/finance")

    assert orders_response.status_code == 200
    assert finance_response.status_code == 403
    with admin_client.application.app_context():
        manager = User.query.filter_by(email="manager@bakery.com").first()
        denied = AuditLog.query.filter_by(
            actor_id=manager.id,
            action="admin_permission_denied",
            entity_type="AdminRoute",
        ).first()
        assert denied is not None
        assert "finance" in (denied.after_value or denied.metadata_json or "")


def test_staff_navigation_hides_manager_owner_sections(admin_client):
    create_admin_user(admin_client.application, "staff@bakery.com", "staff")
    sign_in(admin_client, "staff@bakery.com", "AdminTier1")

    response = admin_client.get("/admin/")

    assert response.status_code == 200
    assert b"All Orders" in response.data
    assert b"Inventory" in response.data
    assert b"Finance" not in response.data
    assert b"Audit Log" not in response.data
    assert b"Analytics" not in response.data
    assert b"Staff</a>" not in response.data


def test_owner_can_create_manager_admin_account(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        "/admin/staff/add",
        data={
            "name": "Floor Manager",
            "email": "floor.manager@bakery.com",
            "phone": "9000000000",
            "admin_tier": "manager",
            "password": "FloorPass1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with admin_client.application.app_context():
        user = User.query.filter_by(email="floor.manager@bakery.com").first()
        assert user is not None
        assert user.role == "admin"
        assert user.admin_tier == "manager"
