from decimal import Decimal

from models import Category, Product, ProductVariant, RawMaterial, db


def sign_in(test_client, email="admin@bakery.com", password="Admin@bakery"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_product_pause_resume_and_delete_actions_render_for_inactive_products(app_factory):
    app = app_factory("admin")
    client = app.test_client()
    with app.app_context():
        category = Category(name="Admin Action Category", icon="box")
        product = Product(
            name="Admin Action Product",
            base_price=Decimal("49"),
            category=category,
            is_active=True,
        )
        variant = ProductVariant(product=product, name="Default", price=Decimal("49"), stock=3)
        db.session.add_all([category, product, variant])
        db.session.commit()
        product_id = product.id

    sign_in(client)

    paused = client.post(f"/admin/products/{product_id}/delete", follow_redirects=True)
    assert paused.status_code == 200
    assert b"Resume" in paused.data
    assert b"Delete" in paused.data
    with app.app_context():
        assert db.session.get(Product, product_id).is_active is False

    resumed = client.post(f"/admin/products/{product_id}/delete", follow_redirects=True)
    assert resumed.status_code == 200
    with app.app_context():
        assert db.session.get(Product, product_id).is_active is True

    client.post(f"/admin/products/{product_id}/delete", follow_redirects=True)
    removed = client.post(f"/admin/products/{product_id}/remove", follow_redirects=True)
    assert removed.status_code == 200
    with app.app_context():
        assert db.session.get(Product, product_id) is None


def test_category_edit_and_delete_controls_update_empty_categories(app_factory):
    app = app_factory("admin")
    client = app.test_client()
    with app.app_context():
        category = Category(name="Seasonal Test", icon="star")
        db.session.add(category)
        db.session.commit()
        category_id = category.id

    sign_in(client)

    page = client.get("/admin/categories")
    assert page.status_code == 200
    assert b"Edit Category" in page.data
    assert b"Delete Category" in page.data

    edited = client.post(
        f"/admin/categories/{category_id}/edit",
        data={"name": "Seasonal Specials", "icon": "cake"},
        follow_redirects=True,
    )
    assert edited.status_code == 200
    assert b"Seasonal Specials" in edited.data

    deleted = client.post(f"/admin/categories/{category_id}/delete", follow_redirects=True)
    assert deleted.status_code == 200
    with app.app_context():
        assert db.session.get(Category, category_id) is None


def test_category_delete_blocks_categories_that_still_have_products(app_factory):
    app = app_factory("admin")
    client = app.test_client()
    with app.app_context():
        category = Category(name="Protected Category", icon="cake")
        product = Product(
            name="Protected Product",
            base_price=Decimal("80"),
            category=category,
            is_active=True,
        )
        db.session.add_all([category, product])
        db.session.commit()
        category_id = category.id

    sign_in(client)
    response = client.post(f"/admin/categories/{category_id}/delete", follow_redirects=True)
    assert response.status_code == 200
    assert b"Move products out of this category" in response.data
    with app.app_context():
        assert db.session.get(Category, category_id) is not None


def test_inventory_product_and_material_subsections_render_full_width(app_factory):
    app = app_factory("admin")
    client = app.test_client()
    with app.app_context():
        category = Category(name="Inventory Section Category", icon="cake")
        product = Product(
            name="Inventory Section Cake",
            base_price=Decimal("120"),
            category=category,
            is_active=True,
        )
        variant = ProductVariant(product=product, name="Slice", price=Decimal("120"), stock=8)
        material = RawMaterial(
            name="Inventory Section Flour",
            unit="kg",
            stock=Decimal("12"),
            reorder_level=Decimal("2"),
            cost_per_unit=Decimal("40"),
            is_active=True,
        )
        db.session.add_all([category, product, variant, material])
        db.session.commit()

    sign_in(client)

    products = client.get("/admin/inventory?view=products")
    assert products.status_code == 200
    assert b"Full-screen product stock" in products.data
    assert b"Inventory Section Cake" in products.data
    assert b"Details" in products.data
    assert b"Edit" in products.data

    materials = client.get("/admin/inventory?view=materials")
    assert materials.status_code == 200
    assert b"Full-screen material stock" in materials.data
    assert b"Inventory Section Flour" in materials.data
    assert b"Details" in materials.data
    assert b"Edit" in materials.data
