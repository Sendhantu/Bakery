import json
from datetime import date

from models import User, db


def sign_in(test_client, email, password, follow_redirects=False):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=follow_redirects,
    )


def test_force_password_change_requires_login(admin_client):
    response = admin_client.get("/auth/force-password-change", follow_redirects=False)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_admin_created_staff_must_change_password_before_admin_access(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        "/admin/staff/add",
        data={
            "name": "First Login Staff",
            "email": "first.login.staff@test.com",
            "phone": "9000001111",
            "staff_address": "14 Oven Street",
            "date_of_joining": "2026-08-03",
            "designation": "Counter Supervisor",
            "emergency_contact": "9000002222",
            "staff_notes": "Morning shift lead",
            "role": "admin",
            "admin_tier": "staff",
            "portal_access": ["dashboard", "orders", "support"],
            "password": "TempPass1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Temporary password" in response.data

    with admin_client.application.app_context():
        staff = User.query.filter_by(email="first.login.staff@test.com").first()
        assert staff is not None
        assert staff.email_locked is True
        assert staff.staff_address == "14 Oven Street"
        assert staff.date_of_joining == date(2026, 8, 3)
        assert staff.designation == "Counter Supervisor"
        assert staff.emergency_contact == "9000002222"
        assert staff.staff_notes == "Morning shift lead"
        assert json.loads(staff.permissions) == ["dashboard", "orders", "support"]
        assert staff.must_change_password is True
        assert staff.check_password("TempPass1")

    admin_client.get("/auth/logout")
    login_response = sign_in(admin_client, "first.login.staff@test.com", "TempPass1")

    assert login_response.status_code == 302
    assert login_response.headers["Location"].endswith("/auth/force-password-change")

    blocked_response = admin_client.get("/admin/orders", follow_redirects=False)
    assert blocked_response.status_code == 302
    assert blocked_response.headers["Location"].endswith("/auth/force-password-change")

    page_response = admin_client.get("/auth/force-password-change")
    assert page_response.status_code == 200
    assert b"Change your temporary password" in page_response.data

    same_password_response = admin_client.post(
        "/auth/force-password-change",
        data={"password": "TempPass1", "confirm_password": "TempPass1"},
        follow_redirects=True,
    )
    assert same_password_response.status_code == 200
    assert b"different from the temporary password" in same_password_response.data

    change_response = admin_client.post(
        "/auth/force-password-change",
        data={"password": "NewStaffPass1", "confirm_password": "NewStaffPass1"},
        follow_redirects=False,
    )
    assert change_response.status_code == 302
    assert change_response.headers["Location"].endswith("/admin/")

    with admin_client.application.app_context():
        db.session.expire_all()
        staff = User.query.filter_by(email="first.login.staff@test.com").first()
        assert staff.must_change_password is False
        assert staff.check_password("NewStaffPass1")
        assert not staff.check_password("TempPass1")

    allowed_response = admin_client.get("/admin/orders")
    assert allowed_response.status_code == 200


def test_branch_employee_creation_and_password_reset_require_change(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    with admin_client.application.app_context():
        from models import Branch

        branch = Branch(name="Password Branch", phone="9000002222")
        db.session.add(branch)
        db.session.commit()
        branch_id = branch.id

    add_response = admin_client.post(
        f"/admin/branches/{branch_id}/employees/add",
        data={
            "name": "Password Cashier",
            "email": "password.cashier@test.com",
            "phone": "9000003333",
            "role": "cashier",
            "staff_address": "Branch counter desk",
            "date_of_joining": "2026-08-03",
            "designation": "Cashier",
            "emergency_contact": "9000004444",
            "password": "Cashier123",
        },
        follow_redirects=True,
    )
    assert add_response.status_code == 200

    with admin_client.application.app_context():
        employee = User.query.filter_by(email="password.cashier@test.com").first()
        assert employee is not None
        employee_id = employee.id
        assert employee.email_locked is True
        assert employee.staff_address == "Branch counter desk"
        assert employee.date_of_joining == date(2026, 8, 3)
        assert employee.designation == "Cashier"
        assert employee.emergency_contact == "9000004444"
        assert json.loads(employee.permissions) == ["pos"]
        assert employee.must_change_password is True

        employee.must_change_password = False
        db.session.commit()

    edit_response = admin_client.post(
        f"/admin/branches/{branch_id}/employees/{employee_id}/edit",
        data={
            "name": "Password Cashier",
            "email": "password.cashier@test.com",
            "phone": "9000003333",
            "role": "cashier",
            "access_status": "active",
            "password": "ResetPass1",
        },
        follow_redirects=True,
    )
    assert edit_response.status_code == 200

    with admin_client.application.app_context():
        employee = db.session.get(User, employee_id)
        assert employee.must_change_password is True
        assert employee.check_password("ResetPass1")
