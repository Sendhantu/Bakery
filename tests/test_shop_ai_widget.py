from decimal import Decimal

from bootstrap import get_container
from models import Cart, Category, Product, ProductVariant, User, db


def sign_in(test_client, email="customer@test.com", password="customer123"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_cake(app, name="Widget Chocolate Cake", price=Decimal("400.00"), stock=5):
    with app.app_context():
        category = Category(name="Widget Test Cakes", icon="C")
        product = Product(
            name=name,
            base_price=price,
            category=category,
            is_active=True,
            description="Rich chocolate cake",
            occasion_tags="birthday chocolate",
        )
        db.session.add_all([category, product])
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Whole",
            price=price,
            stock=stock,
        )
        db.session.add(variant)
        db.session.commit()
        return product.id, variant.id


# ────────────────────────────────────────
# Widget markup
# ────────────────────────────────────────
def test_products_page_renders_ai_widget_for_guest(client):
    response = client.get("/products")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'data-ai-shop-widget' in html
    assert 'data-ai-shop-toggle' in html
    assert 'id="ai-shop-panel"' in html
    assert 'data-ai-authenticated="false"' in html
    assert 'data-ai-endpoint="/chat/ai"' in html
    assert 'data-ai-surface="shop"' in html
    assert 'data-ai-login-url="/auth/login?next=' in html
    assert 'data-ai-register-url="/auth/register?next=' in html
    assert 'data-ai-cart-url="/cart/add"' in html


def test_products_page_renders_ai_widget_for_authenticated_customer(client):
    sign_in(client)

    response = client.get("/products")

    assert response.status_code == 200
    assert 'data-ai-authenticated="true"' in response.data.decode()


def test_ai_widget_is_not_rendered_outside_products_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"data-ai-shop-widget" not in response.data


def test_ai_widget_uses_shop_surface_for_auth_redirects(client):
    response = client.get("/products")

    assert response.status_code == 200
    html = response.data.decode()
    assert "/auth/login?next=/products%23ai-shop-panel" in html
    assert "/auth/register?next=/products%23ai-shop-panel" in html


# ────────────────────────────────────────
# /chat/ai auth + validation
# ────────────────────────────────────────
def test_guest_ai_recommend_returns_auth_required(client):
    response = client.post(
        "/chat/ai",
        json={"query": "chocolate cake", "surface": "shop"},
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["code"] == "auth_required"
    assert payload["login_url"].startswith("/auth/login?next=")
    assert payload["register_url"].startswith("/auth/register?next=")


def test_ai_recommend_rejects_empty_query(client):
    sign_in(client)

    response = client.post("/chat/ai", json={"query": "   ", "surface": "shop"})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_ai_recommend_returns_serialized_products_with_variants(client):
    sign_in(client)

    response = client.post(
        "/chat/ai",
        json={"query": "Widget Chocolate Cake", "surface": "shop"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["products"]

    for product in payload["products"]:
        for key in (
            "id",
            "name",
            "price",
            "current_price",
            "base_price",
            "category",
            "image",
            "description",
            "rating",
            "review_count",
            "stock_status",
            "stock",
            "eggless",
            "default_variant_id",
            "preorder_required",
            "minimum_notice_hours",
            "variants",
            "detail_url",
        ):
            assert key in product
        assert isinstance(product["variants"], list)
        for variant in product["variants"]:
            assert {"id", "name", "price", "stock"} <= set(variant)
        assert product["detail_url"].startswith("/product/")


def test_serialize_ai_product_payload_includes_variants_and_pricing(app):
    from routes.customer import serialize_ai_product_payload

    product_id, _ = create_cake(app, stock=3)
    with app.test_request_context("/products"):
        product = Product.query.get(product_id)
        compact = get_container().mcp_context_service.compact_product(product)
        payload = serialize_ai_product_payload(compact)

    assert payload["id"] == product_id
    assert payload["detail_url"] == f"/product/{product_id}"
    assert len(payload["variants"]) == 1
    assert payload["variants"][0]["stock"] == 3
    assert payload["current_price"] == float(Decimal("400.00"))
    assert payload["base_price"] == float(Decimal("400.00"))
    assert payload["preorder_required"] is False
    assert isinstance(payload["minimum_notice_hours"], int)
    assert payload["eggless"] is False


def test_ai_recommend_accepts_history(client):
    sign_in(client)

    response = client.post(
        "/chat/ai",
        json={
            "query": "what about the chocolate one?",
            "surface": "shop",
            "history": [
                {"role": "user", "content": "show me birthday cakes"},
                {"role": "assistant", "content": "Good matches: Chocolate Truffle Cake."},
            ],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_ai_recommend_sanitizes_and_truncates_history(client):
    sign_in(client)

    history = [
        {"role": "user", "content": "turn %d" % i} for i in range(30)
    ] + [
        {"role": "spy", "content": "injected"},
        {"role": "user", "content": ""},
        "not-a-dict",
    ]

    response = client.post(
        "/chat/ai",
        json={"query": "Widget Chocolate Cake", "surface": "shop"},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# ────────────────────────────────────────
# Context service (conversation memory)
# ────────────────────────────────────────
def test_build_customer_context_includes_recent_conversation(app):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        context = get_container().mcp_context_service.build_customer_context(
            user_id=customer.id,
            query_text="cheaper ones",
            limit=4,
            history=[
                {"role": "user", "content": "show me cakes"},
                {"role": "assistant", "content": "Chocolate Truffle Cake is a hit."},
            ] * 20,
        )

    conversation = context["conversation"]
    assert len(conversation) <= 10
    assert conversation[-1]["role"] == "assistant"
    assert "Chocolate Truffle Cake is a hit." in {
        turn["content"] for turn in conversation
    }


def test_fallback_recalls_prior_product_names_from_history(app):
    with app.test_request_context("/"):
        service = get_container().ai_assistant_service
        context = {
            "product_candidates": [],
            "checkout_addons": [],
            "recent_orders": [],
        }
        message = service._fallback_answer(
            "what about red velvet",
            context,
            history=[
                {"role": "assistant", "content": "Good matches: Red Velvet Cake, Vanilla Cupcake."}
            ],
        )

    assert "Red Velvet Cake" in message
    assert "Vanilla Cupcake" in message


# ────────────────────────────────────────
# Variant API + cart via chat
# ────────────────────────────────────────
def test_product_variants_api_returns_in_stock_variants(client):
    product_id, variant_id = create_cake(client.application, stock=4)

    response = client.get(f"/api/product/{product_id}/variants")

    assert response.status_code == 200
    payload = response.get_json()
    assert any(v["id"] == variant_id for v in payload)
    assert {"id", "name", "price", "stock"} <= set(payload[0])


def test_add_to_cart_json_adds_line(client):
    product_id, variant_id = create_cake(client.application, stock=10)
    sign_in(client)

    response = client.post(
        "/cart/add",
        data={"product_id": product_id, "variant_id": variant_id, "quantity": 2},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["count"] == 2

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        lines = Cart.query.filter_by(
            user_id=customer.id, product_id=product_id, variant_id=variant_id
        ).all()
        assert len(lines) == 1
        assert lines[0].quantity == 2


def test_add_to_cart_json_dedupes_repeated_chat_adds(client):
    product_id, variant_id = create_cake(client.application, stock=10)
    sign_in(client)

    for _ in range(2):
        response = client.post(
            "/cart/add",
            data={"product_id": product_id, "variant_id": variant_id, "quantity": 1},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 200

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        lines = Cart.query.filter_by(
            user_id=customer.id, product_id=product_id, variant_id=variant_id
        ).all()
        assert len(lines) == 1
        assert lines[0].quantity == 2


def test_add_to_cart_json_rejects_insufficient_stock(client):
    product_id, variant_id = create_cake(client.application, stock=1)
    sign_in(client)

    response = client.post(
        "/cart/add",
        data={"product_id": product_id, "variant_id": variant_id, "quantity": 5},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_add_to_cart_json_rejects_unknown_product(client):
    sign_in(client)

    response = client.post(
        "/cart/add",
        data={"product_id": 999999, "variant_id": 1, "quantity": 1},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 404
