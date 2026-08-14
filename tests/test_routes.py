"""Route and portal smoke tests."""

from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

from flask import render_template

from exceptions import ValidationError
from models import (
    Branch,
    Cart,
    Category,
    Coupon,
    COUPON_AUDIENCE_NEW_CUSTOMERS,
    COUPON_AUDIENCE_RETURNING_CUSTOMERS,
    Delivery,
    DeliveryAgent,
    DeliveryCashLedger,
    InventoryForecast,
    LoyaltyLedger,
    Order,
    OrderItem,
    Product,
    ProductMaterial,
    ProductVariant,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    Review,
    SavedAddress,
    SalaryRecord,
    Supplier,
    User,
    Vendor,
    VendorProduct,
    Wishlist,
    db,
)
from clock import utcnow
from services import storage_service as storage_service_module
from services.slot_service import SlotService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_order(app, status="PLACED", assign_delivery=False):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status=status,
            subtotal=250,
            total=250,
            address_line1="12 Test Street",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
        )
        db.session.add(order)
        db.session.flush()

        if assign_delivery:
            agent = DeliveryAgent.query.first()
            assert agent is not None
            db.session.add(
                Delivery(
                    order_id=order.id,
                    agent_id=agent.id,
                    assigned_time=utcnow(),
                    status="ASSIGNED",
                )
            )

        db.session.commit()
        return order.id


def create_customer_order_for_cancel(app, *, placed_at, status="PLACED"):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status=status,
            payment_status="PENDING",
            subtotal=Decimal("250"),
            total=Decimal("250"),
            address_line1="12 Test Street",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
            placed_at=placed_at,
        )
        db.session.add(order)
        db.session.commit()
        return order.id


def add_checkout_cart_item(app, *, customer_email="customer@test.com", price="120"):
    with app.app_context():
        customer = User.query.filter_by(email=customer_email).first()
        assert customer is not None
        product = Product(
            name=f"Coupon Test Cake {customer.id}",
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
                user_id=customer.id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()
        return product.id


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Sweet" in response.data or b"sweet" in response.data.lower()
    assert b"Order by 3PM" not in response.data
    assert b"same-day delivery" not in response.data
    assert b"2-Hour Delivery" not in response.data
    assert b"Choose a convenient delivery slot at checkout" in response.data
    assert b"Slot Delivery" in response.data


def test_homepage_shows_signed_in_customer(client):
    sign_in(client, "customer@test.com", "customer123")

    response = client.get("/")

    assert response.status_code == 200
    assert b'data-authenticated="true"' in response.data
    assert b"Signed in as" in response.data
    assert b">Profile</a>" in response.data


def test_products_page(client):
    response = client.get("/products")
    assert response.status_code == 200


def test_pagination_include_has_default_page_url(client):
    class DummyPagination:
        pages = 2
        page = 1
        has_prev = False
        has_next = True
        prev_num = 1
        next_num = 2

        def iter_pages(self, **_kwargs):
            return [1, 2]

    with client.application.test_request_context(
        "/products?q=Pagination+Fallback&sort=price_asc"
    ):
        html = render_template(
            "includes/pagination.html",
            pagination=DummyPagination(),
        )

    assert "page=2" in html
    assert "Next" in html


def test_customer_products_search_sort_category_and_preferences(client):
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        cake_category = Category(name="Search Suite Cakes", icon="🎂")
        bread_category = Category(name="Search Suite Breads", icon="🍞")
        db.session.add_all([cake_category, bread_category])
        db.session.flush()

        budget = Product(
            name="Search Suite Budget Brownie",
            description="almond cocoa square",
            base_price=Decimal("120"),
            category_id=cake_category.id,
            is_active=True,
        )
        premium = Product(
            name="Search Suite Premium Gateau",
            description="almond celebration layer",
            base_price=Decimal("360"),
            category_id=cake_category.id,
            is_active=True,
        )
        bread = Product(
            name="Search Suite Rustic Loaf",
            description="almond sourdough loaf",
            base_price=Decimal("80"),
            category_id=bread_category.id,
            is_active=True,
        )
        db.session.add_all([budget, premium, bread])
        db.session.flush()

        db.session.add_all(
            [
                ProductVariant(
                    product_id=budget.id,
                    name="Standard",
                    price=budget.base_price,
                    stock=8,
                ),
                ProductVariant(
                    product_id=premium.id,
                    name="Standard",
                    price=premium.base_price,
                    stock=8,
                ),
                ProductVariant(
                    product_id=bread.id,
                    name="Standard",
                    price=bread.base_price,
                    stock=8,
                ),
                Review(
                    product_id=budget.id,
                    user_id=customer.id,
                    rating=2,
                    comment="Okay",
                ),
                Review(
                    product_id=premium.id,
                    user_id=customer.id,
                    rating=5,
                    comment="Excellent",
                ),
                Wishlist(user_id=customer.id, product_id=premium.id),
            ]
        )
        db.session.commit()
        cake_category_id = cake_category.id

    price_response = client.get("/products?q=Search+Suite&sort=price_asc")
    assert price_response.status_code == 200
    price_html = price_response.data.decode()
    assert price_html.index("Search Suite Rustic Loaf") < price_html.index(
        "Search Suite Budget Brownie"
    )
    assert price_html.index("Search Suite Budget Brownie") < price_html.index(
        "Search Suite Premium Gateau"
    )
    assert 'name="q"' in price_html
    assert "Recommended" in price_html

    category_response = client.get(
        f"/products?q=Search+Suite&category={cake_category_id}&sort=price_asc"
    )
    assert category_response.status_code == 200
    category_html = category_response.data.decode()
    assert "Search Suite Budget Brownie" in category_html
    assert "Search Suite Premium Gateau" in category_html
    assert "Search Suite Rustic Loaf" not in category_html

    rating_response = client.get("/products?q=Search+Suite&sort=rating")
    assert rating_response.status_code == 200
    rating_html = rating_response.data.decode()
    assert rating_html.index("Search Suite Premium Gateau") < rating_html.index(
        "Search Suite Budget Brownie"
    )

    sign_in(client, "customer@test.com", "customer123")
    recommended_response = client.get("/products?q=Search+Suite&sort=recommended")
    assert recommended_response.status_code == 200
    recommended_html = recommended_response.data.decode()
    assert recommended_html.index("Search Suite Premium Gateau") < recommended_html.index(
        "Search Suite Budget Brownie"
    )


def test_customer_products_pagination_makes_all_matching_products_reachable(client):
    with client.application.app_context():
        category = Category(name="Pagination Suite Cakes", icon="🎂")
        db.session.add(category)
        db.session.flush()

        for index in range(30):
            product = Product(
                name=f"Pagination Suite Product {index:02d}",
                description="visible pagination check",
                base_price=Decimal(str(100 + index)),
                category_id=category.id,
                is_active=True,
            )
            db.session.add(product)
            db.session.flush()
            db.session.add(
                ProductVariant(
                    product_id=product.id,
                    name="Standard",
                    price=product.base_price,
                    stock=8,
                )
            )
        db.session.commit()

    page_one_response = client.get("/products?q=Pagination+Suite&sort=price_asc")
    assert page_one_response.status_code == 200
    page_one_html = page_one_response.data.decode()
    assert "30 delicious items found" in page_one_html
    assert "Showing 1-24 of 30" in page_one_html
    assert "Pagination Suite Product 00" in page_one_html
    assert "Pagination Suite Product 24" not in page_one_html
    assert "Next" in page_one_html
    assert "page=2" in page_one_html

    page_two_response = client.get(
        "/products?q=Pagination+Suite&sort=price_asc&page=2"
    )
    assert page_two_response.status_code == 200
    page_two_html = page_two_response.data.decode()
    assert "Showing 25-30 of 30" in page_two_html
    assert "Pagination Suite Product 24" in page_two_html
    assert "Pagination Suite Product 29" in page_two_html


def test_customer_base_does_not_trigger_offline_sync_for_customer_pages(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"['admin', 'delivery'].includes(pageRole)" in response.data
    assert b"X-CSRFToken" in response.data


def test_internal_offline_sync_handles_missing_auth_when_csrf_enabled(client):
    client.application.config["WTF_CSRF_ENABLED"] = True
    response = client.post("/internal/trigger_offline_sync")
    assert response.status_code == 401
    assert response.get_json()["status"] == "unauthenticated"


def test_customer_checkout_page_loads(client):
    sign_in(client, "customer@test.com", "customer123")

    add_response = client.post(
        "/cart/add",
        data={"product_id": "1", "variant_id": "1", "quantity": "1"},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    response = client.get("/checkout")
    assert response.status_code == 200
    assert b"Checkout" in response.data
    assert b"Delivery Address" in response.data
    assert b"Use Exact Location" in response.data
    assert b'name="csrf_token"' in response.data
    assert f'min="{utcnow().date().isoformat()}"'.encode() in response.data
    assert b"Same-day delivery is available" in response.data


def test_checkout_saved_address_keeps_manual_address_fields_blank(client):
    sign_in(client, "customer@test.com", "customer123")
    add_response = client.post(
        "/cart/add",
        data={"product_id": "1", "variant_id": "1", "quantity": "1"},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            SavedAddress(
                user_id=customer.id,
                label="Home",
                address_line1="E6E, Asta AVM",
                address_line2="Vadapalani",
                city="Chennai",
                pincode="600072",
                phone="6381232125",
                is_default=True,
            )
        )
        db.session.commit()

    response = client.get("/checkout")

    assert response.status_code == 200
    assert b'value="E6E, Asta AVM"' not in response.data
    assert b'value="Vadapalani"' not in response.data
    assert b'id="checkout-new-address-fields" class="hidden"' in response.data
    assert b'id="checkout-address-line1" name="address_line1" data-required-for-new-address="true"' in response.data


def test_delivery_slot_allows_today_future_slot_only():
    service = SlotService(["09:00 - 11:00", "11:00 - 13:00", "13:00 - 15:00"])
    now = datetime(2026, 7, 29, 10, 30)
    today = now.date()

    assert (
        service.validate_delivery_selection(
            today, "11:00 - 13:00", now=now
        )
        == "11:00 - 13:00"
    )
    try:
        service.validate_delivery_selection(today, "09:00 - 11:00", now=now)
        raised = False
    except ValidationError:
        raised = True

    assert raised is True


def test_robots_txt(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert b"User-agent" in response.data


def test_customer_login_page(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Welcome Back" in response.data


def test_customer_register_page_exposes_csrf_token_meta(client):
    response = client.get("/auth/register")
    assert response.status_code == 200
    assert b'name="csrf-token"' in response.data
    assert b'name="csrf_token"' in response.data


def test_customer_register_page_get_requests_do_not_hit_rate_limit(client):
    responses = [client.get("/auth/register") for _ in range(8)]
    assert all(response.status_code == 200 for response in responses)


def test_admin_login_page(admin_client):
    response = admin_client.get("/auth/login")
    assert response.status_code == 200
    assert b"Admin Sign In" in response.data
    assert b"Available credentials" not in response.data
    assert b"terminal output" not in response.data


def test_delivery_login_page(delivery_client):
    response = delivery_client.get("/auth/login")
    assert response.status_code == 200
    assert b"Delivery Sign In" in response.data
    assert b"Available credentials" not in response.data
    assert b"terminal output" not in response.data


def test_customer_login_form_submits_and_redirects(client):
    response = sign_in(client, "customer@test.com", "customer123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_login_form_preserves_next_destination(client):
    response = client.get("/auth/login?next=/checkout")
    assert response.status_code == 200
    assert b'action="/auth/login?next=/checkout"' in response.data


def test_wrong_role_login_redirects_admin_to_admin_portal(client):
    response = sign_in(client, "admin@bakery.com", "Admin@bakery")
    assert response.status_code == 302
    assert response.headers["Location"] == "http://127.0.0.1:5001/admin/"


def test_wrong_role_login_redirects_delivery_to_delivery_portal(admin_client):
    response = sign_in(admin_client, "delivery@bakery.com", "delivery123")
    assert response.status_code == 302
    assert response.headers["Location"] == "http://127.0.0.1:5002/delivery/"


def test_admin_can_create_delivery_account(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.post(
        "/admin/agents/add",
        data={
            "name": "Rider One",
            "phone": "9000000001",
            "email": "rider.one@bakery.com",
            "password": "RiderPass1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Delivery account created for Rider One" in response.data

    with admin_client.application.app_context():
        user = User.query.filter_by(email="rider.one@bakery.com").first()
        assert user is not None
        assert user.role == "delivery"
        agent = DeliveryAgent.query.filter_by(user_id=user.id).first()
        assert agent is not None
        assert agent.name == "Rider One"


def test_admin_agents_page_hides_create_form_by_default(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.get("/admin/agents")

    assert response.status_code == 200
    assert b"Existing Rider Accounts" in response.data
    assert b'data-toggle-target="#add-agent-form"' in response.data
    assert b'id="add-agent-form"' in response.data
    assert b'card mb-4 hidden" id="add-agent-form"' in response.data


def test_admin_branches_page_shows_expandable_sales_staff_and_reviews(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        branch = Branch(
            name="Details Branch",
            manager_name="Nila Manager",
            phone="9000003333",
            address="12 Branch Street",
        )
        product = Product(
            name="Details Review Cake",
            base_price=Decimal("300"),
            is_active=True,
        )
        db.session.add_all([branch, product])
        db.session.flush()

        employee = User(
            name="Branch Baker",
            email="branch.baker@test.com",
            role="kitchen_staff",
            branch_id=branch.id,
        )
        employee.set_password("StaffPass1")
        rider = DeliveryAgent(
            name="Details Rider",
            phone="9000004444",
            branch_id=branch.id,
            availability=True,
        )
        db.session.add_all([employee, rider])
        db.session.flush()

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            branch_id=branch.id,
            status="DELIVERED",
            payment_status="PAID",
            subtotal=Decimal("600"),
            total=Decimal("600"),
            placed_at=utcnow(),
        )
        db.session.add(order)
        db.session.flush()

        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                variant_name="Standard",
                quantity=2,
                unit_price=Decimal("300"),
                subtotal=Decimal("600"),
            )
        )
        db.session.add(
            Review(
                product_id=product.id,
                user_id=customer.id,
                rating=5,
                comment="Fresh and fast",
            )
        )
        db.session.commit()
        branch_id = branch.id
        employee_id = employee.id
        order_number = order.order_number

    response = admin_client.get("/admin/branches")

    assert response.status_code == 200
    assert b"Details Branch" in response.data
    assert b"Click for branch details" in response.data
    assert b"Total Sales" in response.data
    assert b"Employees" in response.data
    assert b"Add Employee" in response.data
    assert f"/admin/branches/{branch_id}/employees/add".encode() in response.data
    assert f"branch-employee-edit-{branch_id}-{employee_id}".encode() in response.data
    assert b"Branch Baker" in response.data
    assert b"Delivery Agents" in response.data
    assert b"Details Rider" in response.data
    assert b"Recent Sales" in response.data
    assert b"This Week" in response.data
    assert f"/admin/orders?branch_id={branch_id}".encode() in response.data
    assert b"Customer Reviews" in response.data
    assert f"/admin/reviews?branch_id={branch_id}".encode() in response.data
    assert b"Fresh and fast" in response.data

    sales_response = admin_client.get(f"/admin/orders?branch_id={branch_id}")
    assert sales_response.status_code == 200
    assert b"Branch: Details Branch" in sales_response.data
    assert order_number.encode() in sales_response.data

    reviews_response = admin_client.get(f"/admin/reviews?branch_id={branch_id}")
    assert reviews_response.status_code == 200
    assert b"Branch: Details Branch" in reviews_response.data
    assert b"Fresh and fast" in reviews_response.data


def test_admin_can_add_and_edit_branch_employee_from_branch_page(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        branch = Branch(name="Direct Staff Branch", phone="9000005555")
        db.session.add(branch)
        db.session.commit()
        branch_id = branch.id

    add_response = admin_client.post(
        f"/admin/branches/{branch_id}/employees/add",
        data={
            "name": "Counter Lead",
            "email": "counter.lead@test.com",
            "phone": "9000006666",
            "role": "cashier",
            "staff_address": "10 Branch Lane",
            "date_of_joining": "2026-08-03",
            "designation": "Counter Lead",
            "emergency_contact": "9000008888",
            "portal_access": ["pos"],
            "password": "Counter123",
        },
        follow_redirects=True,
    )

    assert add_response.status_code == 200
    assert b"Counter Lead" in add_response.data
    assert b"Cashier / Order Taking" in add_response.data

    with admin_client.application.app_context():
        employee = User.query.filter_by(email="counter.lead@test.com").first()
        assert employee is not None
        employee_id = employee.id
        assert employee.branch_id == branch_id
        assert employee.role == "cashier"
        assert employee.admin_tier == "staff"
        assert employee.email_locked is True
        assert employee.staff_address == "10 Branch Lane"
        assert employee.designation == "Counter Lead"

    edit_response = admin_client.post(
        f"/admin/branches/{branch_id}/employees/{employee_id}/edit",
        data={
            "name": "Kitchen Lead",
            "email": "kitchen.lead@test.com",
            "phone": "9000007777",
            "role": "kitchen_staff",
            "access_status": "inactive",
            "staff_address": "Kitchen bay",
            "date_of_joining": "2026-08-04",
            "designation": "Kitchen Lead",
            "emergency_contact": "9000009999",
            "portal_access": ["kds", "inventory"],
            "password": "Kitchen123",
        },
        follow_redirects=True,
    )

    assert edit_response.status_code == 200
    assert b"Kitchen Lead" in edit_response.data
    assert b"Kitchen Staff" in edit_response.data
    assert b"Email is locked" in edit_response.data
    assert b"Inactive" in edit_response.data

    with admin_client.application.app_context():
        employee = db.session.get(User, employee_id)
        assert employee.name == "Kitchen Lead"
        assert employee.email == "counter.lead@test.com"
        assert employee.phone == "9000007777"
        assert employee.role == "kitchen_staff"
        assert employee.staff_address == "Kitchen bay"
        assert employee.designation == "Kitchen Lead"
        assert employee.emergency_contact == "9000009999"
        assert employee.is_active is False


def test_admin_suppliers_page_shows_expandable_material_and_purchase_details(
    admin_client,
):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        supplier = Supplier(
            name="Details Supplier",
            contact_name="Maya",
            phone="9000005555",
            email="maya@supplier.test",
            payment_terms="Net 15",
        )
        material = RawMaterial(
            name="Details Cocoa",
            unit="kg",
            stock=Decimal("20"),
            reorder_level=Decimal("5"),
            cost_per_unit=Decimal("90"),
            supplier=supplier.name,
            is_active=True,
        )
        vendor = Vendor(
            name=supplier.name,
            contact_person="Maya",
            phone="9000005555",
            email="maya@supplier.test",
            is_active=True,
        )
        db.session.add_all([supplier, material, vendor])
        db.session.flush()

        purchase_order = PurchaseOrder(
            vendor_id=vendor.id,
            status="received",
            order_date=utcnow().date(),
            received_at=utcnow(),
            gst_rate_percent=Decimal("18"),
        )
        db.session.add(purchase_order)
        db.session.flush()
        db.session.add(
            PurchaseOrderItem(
                purchase_order_id=purchase_order.id,
                raw_material_id=material.id,
                quantity=Decimal("8"),
                unit_cost=Decimal("90"),
            )
        )
        db.session.commit()

    response = admin_client.get("/admin/suppliers")

    assert response.status_code == 200
    assert b"Supplier Directory" in response.data
    assert b'data-toggle-target="#add-supplier-form"' in response.data
    assert b'id="add-supplier-form"' in response.data
    assert b'class="card mb-4 hidden"' in response.data
    assert b"Details Supplier" in response.data
    assert b"Click for supplier details" in response.data
    assert b"Linked Materials" in response.data
    assert b"Details Cocoa" in response.data
    assert b"Purchase Activity" in response.data
    assert b"Last Raw Material Reached" in response.data
    assert b"PO #" in response.data


def test_admin_categories_show_products_and_image_url(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.post(
        "/admin/categories/add",
        data={
            "name": "Seasonal Specials",
            "icon": "🍓",
            "image_url": "https://example.com/strawberry.jpg",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Seasonal Specials" in response.data
    assert b"https://example.com/strawberry.jpg" in response.data

    with admin_client.application.app_context():
        category = Category.query.filter_by(name="Seasonal Specials").first()
        assert category is not None
        product = Product(
            name="Strawberry Tart",
            base_price=275,
            category_id=category.id,
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()

    response = admin_client.get("/admin/categories")
    assert response.status_code == 200
    assert b'data-toggle-target="#add-category-form"' in response.data
    assert b'id="add-category-form" class="card mb-4 hidden"' in response.data
    assert b"Tap a Category to View Products" in response.data
    assert b"Strawberry Tart" in response.data
    assert b"View Products" in response.data


def test_admin_creation_forms_are_hidden_until_requested(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    expectations = [
        (
            "/admin/coupons",
            b'data-toggle-target="#add-coupon-form"',
            b'id="add-coupon-form" class="card mb-4 hidden"',
        ),
        (
            "/admin/pricing",
            b'data-toggle-target="#add-pricing-rule-form"',
            b'id="add-pricing-rule-form" class="card mb-4 hidden"',
        ),
        (
            "/admin/production",
            b'data-toggle-target="#new-production-plan-form"',
            b'id="new-production-plan-form" class="card mb-4 hidden"',
        ),
        (
            "/admin/batches",
            b'data-toggle-target="#log-production-batch-form"',
            b'id="log-production-batch-form" class="card mb-4 hidden"',
        ),
        (
            "/admin/staff",
            b'data-toggle-target="#create-admin-account-form"',
            b'id="create-admin-account-form" class="card hidden"',
        ),
        (
            "/admin/staff",
            b'data-toggle-target="#schedule-shift-form"',
            b'id="schedule-shift-form" class="card hidden"',
        ),
        (
            "/admin/pos",
            b'data-toggle-target="#pos-gift-card-form"',
            b'id="pos-gift-card-form" class="card mt-4 hidden"',
        ),
    ]

    for path, trigger, hidden_form in expectations:
        response = admin_client.get(path)
        assert response.status_code == 200
        assert trigger in response.data
        assert hidden_form in response.data


def test_admin_can_change_product_image_after_posting(
    admin_client,
    client,
    monkeypatch,
    tmp_path,
):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302
    monkeypatch.setattr(storage_service_module, "BASE_DIR", tmp_path)

    with admin_client.application.app_context():
        category = Category.query.first()
        assert category is not None
        product = Product(
            name="Editable Image Cake",
            description="Original description",
            ingredients="Flour, sugar",
            preparation="Bake fresh",
            base_price=Decimal("350"),
            category_id=category.id,
            is_active=True,
        )
        variant = ProductVariant(
            product=product,
            name="Standard",
            price=Decimal("350"),
            stock=8,
        )
        db.session.add_all([product, variant])
        db.session.commit()
        product_id = product.id
        variant_id = variant.id
        category_id = category.id

    edit_response = admin_client.get(f"/admin/products/{product_id}/edit")
    assert edit_response.status_code == 200
    assert b"Frame Fit" in edit_response.data
    assert b"Frame Position" in edit_response.data

    response = admin_client.post(
        f"/admin/products/{product_id}/edit",
        data={
            "name": "Editable Image Cake",
            "description": "Original description",
            "ingredients": "Flour, sugar, cocoa",
            "special_ingredient": "Belgian chocolate",
            "preparation": "Bake fresh",
            "base_price": "350",
            "category_id": str(category_id),
            "egg_preference": "eggless",
            "is_active": "on",
            "minimum_notice_hours": "24",
            "occasion_tags": "",
            "image_url": "",
            "image": (BytesIO(b"replacement cake image"), "replacement cake.png"),
            "image_fit": "contain",
            "image_position": "top",
            "variant_id[]": [str(variant_id)],
            "variant_name[]": ["Standard"],
            "variant_price[]": ["350"],
            "variant_stock[]": ["8"],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Change Image" in response.data
    assert b"/static/uploads/products/editable-image-cake-" in response.data
    assert b"--product-image-fit: contain" in response.data
    assert b"--product-image-position: center top" in response.data

    with admin_client.application.app_context():
        updated = db.session.get(Product, product_id)
        assert updated.image.startswith(
            "/static/uploads/products/editable-image-cake-"
        )
        assert updated.image.endswith(".png")
        assert updated.image_url == updated.image
        saved_path = tmp_path / "static" / updated.image.removeprefix("/static/")
        assert saved_path.read_bytes() == b"replacement cake image"
        assert updated.image_fit == "contain"
        assert updated.image_position == "top"
        assert updated.ingredients == "Flour, sugar, cocoa"
        assert updated.special_ingredient == "Belgian chocolate"
        assert updated.is_eggless is True

    detail_response = client.get(f"/product/{product_id}")
    assert detail_response.status_code == 200
    assert b"Eggless" in detail_response.data
    assert b"Flour" in detail_response.data
    assert b"sugar" in detail_response.data
    assert b"Special Ingredient" in detail_response.data
    assert b"Belgian chocolate" in detail_response.data


def test_admin_dashboard_live_refresh_returns_fragments(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.get(
        "/admin/",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.is_json
    assert "#admin-dashboard-live" in response.json["fragments"]


def test_admin_navigation_header_returns_full_html(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.get(
        "/admin/orders",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "X-Admin-Navigation": "partial",
            "Accept": "text/html",
        },
    )

    assert response.status_code == 200
    assert not response.is_json
    assert b'id="admin-main"' in response.data
    assert b"Orders" in response.data


def test_inventory_forecasts_are_hidden_until_ai_rollout(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    dashboard = admin_client.get("/admin/")
    assert dashboard.status_code == 200
    assert b">Forecasts</a>" not in dashboard.data
    assert b"/admin/forecasts" not in dashboard.data

    with admin_client.application.app_context():
        before_count = InventoryForecast.query.count()

    response = admin_client.get("/admin/forecasts")

    assert response.status_code == 200
    assert b"AI Forecasting Provision" in response.data
    assert b"Predicted Qty" not in response.data
    assert b"Confidence" not in response.data

    with admin_client.application.app_context():
        assert InventoryForecast.query.count() == before_count


def test_kitchen_display_shows_priority_and_queue_orders_only(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        product = Product(
            name="KDS Queue Cake",
            base_price=Decimal("250"),
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()

        priority_order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=Decimal("250"),
            total=Decimal("250"),
            special_note="urgent kitchen priority",
            placed_at=utcnow() - timedelta(minutes=3),
        )
        normal_order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=Decimal("250"),
            total=Decimal("250"),
            placed_at=utcnow() - timedelta(minutes=3),
        )
        packed_order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PACKED",
            subtotal=Decimal("250"),
            total=Decimal("250"),
            placed_at=utcnow() - timedelta(minutes=3),
        )
        db.session.add_all([priority_order, normal_order, packed_order])
        db.session.flush()

        db.session.add_all(
            [
                OrderItem(
                    order_id=priority_order.id,
                    product_id=product.id,
                    product_name="Priority Kitchen Cake",
                    variant_name="Slice",
                    quantity=1,
                    unit_price=Decimal("250"),
                    subtotal=Decimal("250"),
                ),
                OrderItem(
                    order_id=normal_order.id,
                    product_id=product.id,
                    product_name="Normal Queue Cake",
                    variant_name="Slice",
                    quantity=1,
                    unit_price=Decimal("250"),
                    subtotal=Decimal("250"),
                ),
                OrderItem(
                    order_id=packed_order.id,
                    product_id=product.id,
                    product_name="Packed Hidden Cake",
                    variant_name="Slice",
                    quantity=1,
                    unit_price=Decimal("250"),
                    subtotal=Decimal("250"),
                ),
            ]
        )
        db.session.commit()
        priority_id = priority_order.id
        normal_id = normal_order.id

    response = admin_client.get("/admin/kds")

    assert response.status_code == 200
    assert b"Make these first" in response.data
    assert b"Normal kitchen orders" in response.data
    assert b"Priority Kitchen Cake" in response.data
    assert b"Normal Queue Cake" in response.data
    assert b"Packed Hidden Cake" not in response.data
    assert (
        f'data-kds-order="{priority_id}" data-kds-priority="true"'.encode()
        in response.data
    )
    assert (
        f'data-kds-order="{normal_id}" data-kds-priority="false"'.encode()
        in response.data
    )
    assert b"customer@test.com" not in response.data


def test_admin_live_past_orders_split_active_and_closed_orders(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None
        live_order = Order(
            order_number="LIVE-SPLIT-1",
            user_id=customer.id,
            status="PREPARING",
            payment_status="PENDING",
            payment_method="COD",
            subtotal=Decimal("180"),
            total=Decimal("189"),
            gst_amount=Decimal("9"),
            placed_at=utcnow() - timedelta(minutes=15),
        )
        past_order = Order(
            order_number="PAST-SPLIT-1",
            user_id=customer.id,
            status="DELIVERED",
            payment_status="PAID",
            payment_method="UPI",
            subtotal=Decimal("220"),
            total=Decimal("231"),
            gst_amount=Decimal("11"),
            placed_at=utcnow() - timedelta(days=1),
        )
        db.session.add_all([live_order, past_order])
        db.session.commit()

    response = admin_client.get("/admin/orders/live-past?q=SPLIT")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Live & Past Orders" in html
    assert "Live Orders" in html
    assert "Past Orders" in html
    assert "LIVE-SPLIT-1" in html
    assert "PAST-SPLIT-1" in html
    assert html.index("LIVE-SPLIT-1") < html.index("PAST-SPLIT-1")
    assert "PREPARING" in html
    assert "DELIVERED" in html

    fragment_response = admin_client.get(
        "/admin/orders/live-past?q=SPLIT",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
    )
    assert fragment_response.status_code == 200
    payload = fragment_response.get_json()
    assert "#admin-order-monitor-live" in payload["fragments"]
    assert "LIVE-SPLIT-1" in payload["fragments"]["#admin-order-monitor-live"]
    assert "PAST-SPLIT-1" in payload["fragments"]["#admin-order-monitor-live"]


def test_raw_materials_page_shows_readable_material_details(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        material = RawMaterial(
            name="Display Cocoa Powder",
            unit="kg",
            stock=Decimal("12"),
            reorder_level=Decimal("3"),
            cost_per_unit=Decimal("80"),
            supplier="Cocoa Vendor",
            notes="Keep dry",
        )
        db.session.add(material)
        db.session.commit()
        material_id = material.id

    response = admin_client.get("/admin/raw-materials?q=Display")

    assert response.status_code == 200
    assert b"Search" in response.data
    assert b'id="rm-search"' in response.data
    assert b"Create New Raw Material" in response.data
    assert b"raw-material-table" in response.data
    assert b"Raw Material" in response.data
    assert b"Current Stock" in response.data
    assert b"Actions" in response.data
    assert b"Display Cocoa Powder" in response.data
    assert b"Total Materials" in response.data
    assert b"Inventory Value" in response.data

    selected_response = admin_client.get(f"/admin/raw-materials?material_id={material_id}")

    assert selected_response.status_code == 200
    assert b"Display Cocoa Powder" in selected_response.data

    detail_response = admin_client.get(f"/admin/raw-materials/{material_id}")

    assert detail_response.status_code == 200
    assert b"Display Cocoa Powder" in detail_response.data
    assert b"Cocoa Vendor" in detail_response.data
    assert b"Keep dry" in detail_response.data
    assert b"Purchase History" in detail_response.data
    assert b"Stock Movement History" in detail_response.data
    assert b"Batches" in detail_response.data
    assert b"Raw Materials" in detail_response.data

    create_response = admin_client.get("/admin/raw-materials?add=1")

    assert create_response.status_code == 200
    assert b'id="new-raw-material-form" class="card raw-material-create-card"' in create_response.data
    assert b'id="new-raw-material-form" class="card raw-material-create-card hidden"' not in create_response.data


def test_admin_order_detail_shows_valid_status_choices(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    order_id = create_order(admin_client.application, status="PREPARING")
    response = admin_client.get(f"/admin/orders/{order_id}")

    assert response.status_code == 200
    assert b'name="status"' in response.data
    assert b'value="PACKED"' in response.data


def test_admin_can_mark_assigned_cod_order_delivered_without_notification_error(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    order_id = create_order(
        admin_client.application,
        status="OUT_FOR_DELIVERY",
        assign_delivery=True,
    )

    response = admin_client.post(
        f"/admin/orders/{order_id}/update-status",
        data={"status": "DELIVERED"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Order status updated to DELIVERED." in response.data

    with admin_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "DELIVERED"
        assert order.payment_status == "PENDING"
        assert order.delivery.status == "DELIVERED"
        assert order.delivery.delivered_time is not None
        assert (
            LoyaltyLedger.query.filter_by(
                user_id=order.user_id,
                order_id=order.id,
                reason="order_earned",
            ).first()
            is None
        )


def test_delivery_cannot_set_packed_status(delivery_client):
    login_response = sign_in(delivery_client, "delivery@bakery.com", "delivery123")
    assert login_response.status_code == 302

    order_id = create_order(
        delivery_client.application,
        status="PREPARING",
        assign_delivery=True,
    )
    response = delivery_client.post(
        f"/delivery/order/{order_id}/update",
        data={"status": "PACKED"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Invalid delivery status." in response.data

    with delivery_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order is not None
        assert order.status == "PREPARING"


def test_delivery_status_update_reaches_customer_portal_room(
    delivery_client,
    socket_emit_spy,
):
    login_response = sign_in(delivery_client, "delivery@bakery.com", "delivery123")
    assert login_response.status_code == 302

    order_id = create_order(
        delivery_client.application,
        status="OUT_FOR_DELIVERY",
        assign_delivery=True,
    )
    with delivery_client.application.app_context():
        order = db.session.get(Order, order_id)
        customer_id = order.user_id
        agent_id = order.delivery.agent_id

    response = delivery_client.post(
        f"/delivery/order/{order_id}/update",
        data={"status": "DELIVERED"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Status updated to DELIVERED." in response.data

    status_events = [
        (payload, kwargs)
        for event, payload, kwargs in socket_emit_spy
        if event == "order_status_updated"
    ]
    assert status_events
    assert [kwargs["room"] for _payload, kwargs in status_events] == [
        "admin",
        "kds",
        f"customer_{customer_id}",
        f"delivery_{agent_id}",
    ]
    assert all(payload["order_id"] == order_id for payload, _kwargs in status_events)
    assert all(payload["new_status"] == "DELIVERED" for payload, _kwargs in status_events)


def test_admin_triage_page_renders_pending_order_groups(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None

        flour = RawMaterial(
            name="TRIAGE_FLOUR",
            unit="kg",
            stock=Decimal("8"),
            reorder_level=Decimal("3"),
            is_active=True,
        )
        butter = RawMaterial(
            name="TRIAGE_BUTTER",
            unit="kg",
            stock=Decimal("1"),
            reorder_level=Decimal("2"),
            is_active=True,
        )
        db.session.add_all([flour, butter])
        db.session.flush()

        product = Product(name="Cake Slice", base_price=199, is_active=True)
        db.session.add(product)
        db.session.flush()

        db.session.add_all(
            [
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=flour.id,
                    quantity_required=Decimal("2"),
                ),
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=butter.id,
                    quantity_required=Decimal("1"),
                ),
            ]
        )

        order1 = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=200,
            total=200,
            address_line1="12 Test Street",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
            placed_at=utcnow() - timedelta(minutes=15),
        )
        order2 = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=200,
            total=200,
            address_line1="12 Test Street",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
            placed_at=utcnow(),
        )
        db.session.add_all([order1, order2])
        db.session.flush()

        db.session.add_all(
            [
                OrderItem(
                    order_id=order1.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=2,
                    unit_price=Decimal("100"),
                    subtotal=Decimal("200"),
                ),
                OrderItem(
                    order_id=order2.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=3,
                    unit_price=Decimal("100"),
                    subtotal=Decimal("300"),
                ),
            ]
        )
        db.session.commit()

    response = admin_client.get("/admin/triage")
    assert response.status_code == 200
    assert b"Smart Triage" in response.data
    assert (
        b"Fulfillable now" in response.data
        or b"fulfillable now" in response.data.lower()
    )


def test_admin_loyalty_page_renders_config(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.get("/admin/loyalty")
    assert response.status_code == 200
    assert (
        b"10 pts = \xe2\x82\xb910 off" in response.data
        or b"10 pts = Rs" in response.data
    )
    assert b"Large order minimum" in response.data


def test_admin_can_toggle_coupon(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        coupon = Coupon(
            code="PHASE1",
            discount_type="flat",
            discount_value=25,
            min_order_value=0,
            max_uses=10,
        )
        db.session.add(coupon)
        db.session.commit()
        coupon_id = coupon.id

    response = admin_client.post(
        f"/admin/coupons/{coupon_id}/toggle", follow_redirects=True
    )
    assert response.status_code == 200

    with admin_client.application.app_context():
        coupon = db.session.get(Coupon, coupon_id)
        assert coupon is not None
        assert coupon.is_active is False


def test_admin_can_create_coupon_for_returning_customers(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    response = admin_client.post(
        "/admin/coupons/add",
        data={
            "code": "OLDLOVE",
            "discount_type": "flat",
            "discount_value": "40",
            "min_order_value": "0",
            "max_uses": "25",
            "per_user_limit": "2",
            "customer_audience": COUPON_AUDIENCE_RETURNING_CUSTOMERS,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Returning customers" in response.data
    with admin_client.application.app_context():
        coupon = Coupon.query.filter_by(code="OLDLOVE").first()
        assert coupon is not None
        assert coupon.customer_audience == COUPON_AUDIENCE_RETURNING_CUSTOMERS
        assert coupon.first_order_only is False
        assert coupon.per_user_limit == 2


def test_inventory_page_backfills_missing_product_variant(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        product = Product(name="Inventory Sync Cake", base_price=399, is_active=True)
        db.session.add(product)
        db.session.commit()
        product_id = product.id
        assert ProductVariant.query.filter_by(product_id=product_id).count() == 0

    response = admin_client.get("/admin/inventory")
    assert response.status_code == 200

    with admin_client.application.app_context():
        variants = ProductVariant.query.filter_by(product_id=product_id).all()
        assert len(variants) == 1
        assert variants[0].name == "Standard"


def test_inventory_page_shows_product_sales_materials_and_vendor_details(admin_client):
    login_response = sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        branch = Branch(name="Town Center Branch", phone="9000001111")
        material = RawMaterial(
            name="Inventory Almond Flour",
            unit="kg",
            stock=Decimal("12"),
            reorder_level=Decimal("4"),
            cost_per_unit=Decimal("80"),
            is_active=True,
        )
        product = Product(
            name="Inventory Almond Tart",
            base_price=Decimal("250"),
            is_active=True,
        )
        db.session.add_all([branch, material, product])
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            branch_id=branch.id,
            name="Box of 4",
            price=Decimal("250"),
            stock=8,
        )
        vendor = Vendor(
            name="Almond Vendor Co",
            contact_person="Ravi",
            phone="9000002222",
            email="vendor@example.com",
            is_active=True,
        )
        db.session.add_all([variant, vendor])
        db.session.flush()
        db.session.add_all(
            [
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=material.id,
                    quantity_required=Decimal("0.50"),
                ),
                VendorProduct(
                    vendor_id=vendor.id,
                    raw_material_id=material.id,
                    last_unit_cost=Decimal("82"),
                    typical_unit_cost=Decimal("80"),
                ),
            ]
        )
        purchase_order = PurchaseOrder(
            vendor_id=vendor.id,
            status="received",
            order_date=utcnow().date(),
            received_at=utcnow(),
            gst_rate_percent=Decimal("18"),
        )
        db.session.add(purchase_order)
        db.session.flush()
        db.session.add(
            PurchaseOrderItem(
                purchase_order_id=purchase_order.id,
                raw_material_id=material.id,
                quantity=Decimal("5"),
                unit_cost=Decimal("82"),
            )
        )
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            branch_id=branch.id,
            status="DELIVERED",
            payment_status="PAID",
            subtotal=Decimal("1000"),
            total=Decimal("1000"),
            placed_at=utcnow(),
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
                quantity=4,
                unit_price=Decimal("250"),
                subtotal=Decimal("1000"),
            )
        )
        db.session.commit()

    response = admin_client.get("/admin/inventory")

    assert response.status_code == 200
    assert b"Product Inventory" in response.data
    assert b"Raw Material Inventory" in response.data
    assert b"Inventory Almond Tart" in response.data
    assert b"Town Center Branch" in response.data
    assert b"Day" in response.data
    assert b"Week" in response.data
    assert b"Month" in response.data
    assert b"Year" in response.data

    material_response = admin_client.get("/admin/inventory?view=materials")
    assert material_response.status_code == 200
    assert b"Raw Material Inventory" in material_response.data
    assert b"Inventory Almond Flour" in material_response.data
    assert b"Almond Vendor Co" in material_response.data
    assert b"Last Material Received" in material_response.data


def test_reverse_geocode_api_validates_coordinates(client):
    sign_in(client, "customer@test.com", "customer123")

    response = client.get("/api/location/reverse-geocode?lat=abc&lng=123")
    assert response.status_code == 400
    assert response.is_json
    assert response.json["ok"] is False


def test_customer_can_place_pickup_order(client):
    sign_in(client, "customer@test.com", "customer123")

    add_response = client.post(
        "/cart/add",
        data={"product_id": "1", "variant_id": "1", "quantity": "1"},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
            "occasion": "Birthday",
            "special_note": "Pickup at the front counter",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"placed successfully" in response.data

    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        assert order is not None
        assert order.fulfillment_type == "PICKUP"
        assert order.delivery_charge == 0
        assert order.delivery_slot == "09:00 - 11:00"


def test_customer_can_cancel_order_within_two_minutes(client):
    sign_in(client, "customer@test.com", "customer123")
    order_id = create_customer_order_for_cancel(
        client.application,
        placed_at=utcnow() - timedelta(seconds=30),
    )

    response = client.post(
        f"/orders/{order_id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Order cancelled successfully." in response.data
    with client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "CANCELLED"
        assert order.payment_status == "CANCELLED"


def test_customer_cannot_cancel_order_after_two_minutes(client):
    sign_in(client, "customer@test.com", "customer123")
    order_id = create_customer_order_for_cancel(
        client.application,
        placed_at=utcnow() - timedelta(minutes=2, seconds=5),
    )

    response = client.post(
        f"/orders/{order_id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"must be within 2 minutes of placing" in response.data
    with client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "PLACED"
        assert order.payment_status == "PENDING"


def test_customer_orders_page_shows_cancel_only_during_two_minute_window(client):
    sign_in(client, "customer@test.com", "customer123")
    fresh_order_id = create_customer_order_for_cancel(
        client.application,
        placed_at=utcnow() - timedelta(seconds=45),
    )
    expired_order_id = create_customer_order_for_cancel(
        client.application,
        placed_at=utcnow() - timedelta(minutes=3),
    )

    detail_response = client.get(f"/orders/{fresh_order_id}")
    response = client.get("/orders")

    assert detail_response.status_code == 200
    assert b"Cancel window closes in" in detail_response.data
    assert response.status_code == 200
    html = response.data.decode()
    assert f"/orders/{fresh_order_id}/cancel" in html
    assert f"/orders/{expired_order_id}/cancel" not in html


def test_checkout_adds_gst_above_product_price_and_displays_it(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        product = Product(
            name="Tax Display Brownie",
            base_price=Decimal("200"),
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Box",
            price=Decimal("200"),
            stock=5,
        )
        db.session.add(variant)
        db.session.flush()
        db.session.add(
            Cart(
                user_id=customer.id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()

    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"GST" in response.data
    assert b"Order #" in response.data
    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        assert order.subtotal == Decimal("200.00")
        assert order.gst_rate == Decimal("5.00")
        assert order.gst_taxable_amount == Decimal("200.00")
        assert order.cgst_amount == Decimal("5.00")
        assert order.sgst_amount == Decimal("5.00")
        assert order.gst_amount == Decimal("10.00")
        assert order.gst_order_source == "DIRECT_WEB_PICKUP"
        assert order.gst_liability_party == "PAYABLE_BY_BAKERY"
        assert order.total == Decimal("210.00")


def test_welcome_coupon_is_blocked_after_customer_first_order(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            Order(
                order_number=Order.generate_order_number(),
                user_id=customer.id,
                status="DELIVERED",
                subtotal=Decimal("100"),
                total=Decimal("105"),
                address_line1="12 Test Street",
                city="Coimbatore",
                pincode="641002",
                phone="9999999999",
                delivery_slot="09:00 - 11:00",
                delivery_date=utcnow().date() - timedelta(days=1),
            )
        )
        db.session.add(
            Coupon(
                code="WELCOMEONLY",
                discount_type="flat",
                discount_value=Decimal("50"),
                min_order_value=Decimal("0"),
                max_uses=100,
                customer_audience=COUPON_AUDIENCE_NEW_CUSTOMERS,
                first_order_only=True,
            )
        )
        db.session.commit()

    add_checkout_cart_item(client.application, price="120")
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
            "coupon_code": "WELCOMEONLY",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        coupon = Coupon.query.filter_by(code="WELCOMEONLY").first()
        assert order.coupon_code is None
        assert order.discount == Decimal("0.00")
        assert order.gst_amount == Decimal("6.00")
        assert order.total == Decimal("126.00")
        assert coupon.used_count == 0


def test_returning_customer_coupon_applies_after_first_order(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            Order(
                order_number=Order.generate_order_number(),
                user_id=customer.id,
                status="DELIVERED",
                subtotal=Decimal("100"),
                total=Decimal("105"),
                address_line1="12 Test Street",
                city="Coimbatore",
                pincode="641002",
                phone="9999999999",
                delivery_slot="09:00 - 11:00",
                delivery_date=utcnow().date() - timedelta(days=1),
            )
        )
        db.session.add(
            Coupon(
                code="OLDVIP",
                discount_type="flat",
                discount_value=Decimal("40"),
                min_order_value=Decimal("0"),
                max_uses=100,
                customer_audience=COUPON_AUDIENCE_RETURNING_CUSTOMERS,
                per_user_limit=1,
            )
        )
        db.session.commit()

    add_checkout_cart_item(client.application, price="120")
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
            "coupon_code": "OLDVIP",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        coupon = Coupon.query.filter_by(code="OLDVIP").first()
        assert order.coupon_code == "OLDVIP"
        assert order.discount == Decimal("40.00")
        assert order.gst_amount == Decimal("4.00")
        assert order.total == Decimal("84.00")
        assert coupon.used_count == 1


def test_coupon_preview_rejects_welcome_coupon_for_returning_customer(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            Order(
                order_number=Order.generate_order_number(),
                user_id=customer.id,
                status="DELIVERED",
                subtotal=Decimal("100"),
                total=Decimal("105"),
                address_line1="12 Test Street",
                city="Coimbatore",
                pincode="641002",
                phone="9999999999",
                delivery_slot="09:00 - 11:00",
                delivery_date=utcnow().date() - timedelta(days=1),
            )
        )
        db.session.add(
            Coupon(
                code="WELCOMEAPI",
                discount_type="percentage",
                discount_value=Decimal("10"),
                min_order_value=Decimal("0"),
                max_uses=100,
                customer_audience=COUPON_AUDIENCE_NEW_CUSTOMERS,
                first_order_only=True,
            )
        )
        db.session.commit()

    response = client.post(
        "/api/validate-coupon",
        json={"code": "WELCOMEAPI", "subtotal": 120},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is False
    assert "first order" in payload["message"].lower()


def test_preorder_product_blocks_insufficient_notice_pickup(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        product = Product(
            name="Wedding Signature Cake",
            base_price=999,
            preorder_required=True,
            minimum_notice_hours=48,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id, name="Standard", price=999, stock=5
        )
        db.session.add(variant)
        db.session.commit()
        product_id = product.id
        variant_id = variant.id

    add_response = client.post(
        "/cart/add",
        data={
            "product_id": str(product_id),
            "variant_id": str(variant_id),
            "quantity": "1",
        },
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"requires at least 48 hours of preorder notice" in response.data


def test_delivery_can_collect_cod_payment(delivery_client):
    login_response = sign_in(delivery_client, "delivery@bakery.com", "delivery123")
    assert login_response.status_code == 302

    order_id = create_order(
        delivery_client.application,
        status="OUT_FOR_DELIVERY",
        assign_delivery=True,
    )
    response = delivery_client.post(
        f"/delivery/order/{order_id}/collect-payment",
        data={"amount_received": "250", "payment_mode": "CASH"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"COD payment marked as collected." in response.data

    with delivery_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order is not None
        assert order.payment_status == "PAID"
        ledger_entry = DeliveryCashLedger.query.filter_by(order_id=order_id).first()
        assert ledger_entry is not None
        assert ledger_entry.action == "cod_collected"
        assert ledger_entry.amount == Decimal("250.00")
        assert ledger_entry.balance_after == Decimal("250.00")


def test_admin_can_reconcile_delivery_cash_ledger(admin_client, delivery_client):
    assert sign_in(delivery_client, "delivery@bakery.com", "delivery123").status_code == 302
    order_id = create_order(
        delivery_client.application,
        status="OUT_FOR_DELIVERY",
        assign_delivery=True,
    )
    delivery_response = delivery_client.post(
        f"/delivery/order/{order_id}/collect-payment",
        data={"amount_received": "250", "payment_mode": "CASH"},
        follow_redirects=True,
    )
    assert delivery_response.status_code == 200

    assert sign_in(admin_client, "admin@bakery.com", "Admin@bakery").status_code == 302
    ledger_response = admin_client.get("/admin/delivery-cash")
    assert ledger_response.status_code == 200
    assert b"Delivery Cash Ledger" in ledger_response.data
    assert b"COD Collected" in ledger_response.data

    with admin_client.application.app_context():
        ledger_entry = DeliveryCashLedger.query.filter_by(order_id=order_id).first()
        assert ledger_entry is not None
        agent_id = ledger_entry.agent_id

    handover_response = admin_client.post(
        f"/admin/delivery-cash/{agent_id}/handover",
        data={"amount": "100", "notes": "Evening cash deposit"},
        follow_redirects=True,
    )
    assert handover_response.status_code == 200
    assert b"Cash handover recorded" in handover_response.data

    recover_response = admin_client.post(
        f"/admin/delivery-cash/{agent_id}/recover",
        data={
            "amount": "150",
            "recovery_method": "salary_deduction",
            "notes": "Cash shortage after route close",
        },
        follow_redirects=True,
    )
    assert recover_response.status_code == 200
    assert b"Cash shortage recovery recorded" in recover_response.data

    with admin_client.application.app_context():
        latest = (
            DeliveryCashLedger.query.filter_by(agent_id=agent_id)
            .order_by(DeliveryCashLedger.created_at.desc(), DeliveryCashLedger.id.desc())
            .first()
        )
        assert latest is not None
        assert latest.action == "salary_deduction"
        assert latest.balance_after == Decimal("0.00")
        salary_record = SalaryRecord.query.filter_by(status="deducted").first()
        assert salary_record is not None
        assert salary_record.amount == Decimal("-150.00")
