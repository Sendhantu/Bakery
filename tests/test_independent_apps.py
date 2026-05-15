from admin_app.app import APP_PORT as ADMIN_PORT
from admin_app.app import app as admin_app
from customer_app.app import APP_PORT as CUSTOMER_PORT
from customer_app.app import app as customer_app
from delivery_app.app import APP_PORT as DELIVERY_PORT
from delivery_app.app import app as delivery_app


def test_apps_have_independent_ports_and_session_cookies():
    assert CUSTOMER_PORT == 5000
    assert ADMIN_PORT == 5001
    assert DELIVERY_PORT == 5002

    assert customer_app.config["SESSION_COOKIE_NAME"] == "sweetcrumbs_customer_session"
    assert admin_app.config["SESSION_COOKIE_NAME"] == "sweetcrumbs_admin_session"
    assert delivery_app.config["SESSION_COOKIE_NAME"] == "sweetcrumbs_delivery_session"


def test_apps_use_existing_frontend_templates():
    customer_client = customer_app.test_client()
    admin_client = admin_app.test_client()
    delivery_client = delivery_app.test_client()

    customer_response = customer_client.get("/")
    admin_response = admin_client.get("/auth/login")
    delivery_response = delivery_client.get("/auth/login")

    assert customer_app.template_folder.endswith("/templates")
    assert admin_app.template_folder.endswith("/templates")
    assert delivery_app.template_folder.endswith("/templates")

    assert customer_response.status_code == 200
    assert b"Every Occasion" in customer_response.data

    assert admin_response.status_code == 200
    assert b"Admin Sign In" in admin_response.data

    assert delivery_response.status_code == 200
    assert b"Delivery Sign In" in delivery_response.data
