from models import Cart, CustomerActivity, Message, Product, User, db


def sign_in(test_client, email="customer@test.com", password="customer123"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_ai_recommendation_route_uses_fallback_and_tracks_query(client):
    sign_in(client)

    response = client.post(
        "/chat/ai",
        json={"query": "birthday cake under 800 with candles", "surface": "shop"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["source"] == "rules"
    assert payload["products"]
    assert payload["products"][0]["detail_url"].startswith("/product/")
    assert "checkout_addons" in payload

    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        activity = CustomerActivity.query.filter_by(
            user_id=customer.id,
            event_type="ai_query",
        ).first()
        assert activity is not None
        assert "birthday cake" in activity.query_text


def test_home_ai_guest_sees_login_prompt_not_chat(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'data-ai-chat data-ai-endpoint="/chat/ai" data-ai-surface="home"' not in html
    assert "Login Required" in html
    assert "/auth/login?next=" in html

    chat = client.post("/chat/ai", json={"query": "eggless cakes", "surface": "home"})
    assert chat.status_code == 401
    assert chat.get_json()["code"] == "auth_required"


def test_home_ai_uses_inline_chat_component(client):
    sign_in(client)

    response = client.get("/")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'data-ai-chat data-ai-endpoint="/chat/ai" data-ai-surface="home"' in html
    assert "data-ai-chat-form" in html
    assert "data-ai-chat-log" in html
    assert "async function askHomeAI" not in html


def test_support_ai_uses_inline_chat_component(client):
    sign_in(client)

    response = client.get("/chat")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'data-ai-chat data-ai-endpoint="/chat/ai" data-ai-surface="support"' in html
    assert "data-ai-chat-form" in html
    assert "data-ai-chat-log" in html
    assert "async function askBakeryAI" not in html


def test_product_view_activity_is_recorded(client):
    sign_in(client)

    with client.application.app_context():
        product = Product.query.filter_by(is_active=True).first()
        product_id = product.id

    response = client.get(f"/product/{product_id}")

    assert response.status_code == 200
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        activity = CustomerActivity.query.filter_by(
            user_id=customer.id,
            event_type="product_view",
            product_id=product_id,
        ).first()
        assert activity is not None


def test_ai_support_exchange_can_be_stored_when_enabled(client):
    sign_in(client)
    client.application.config["AI_SUPPORT_BOT_ENABLED"] = True

    response = client.post(
        "/chat/ai",
        json={"query": "Can you suggest a cake for a small birthday?"},
    )

    assert response.status_code == 200
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        bot = User.query.filter_by(email="ai-assistant@bakery.local").first()
        assert bot is not None
        assert bot.role == "kitchen_staff"
        assert Message.query.filter_by(
            sender_id=customer.id,
            receiver_id=bot.id,
        ).first()
        assert Message.query.filter_by(
            sender_id=bot.id,
            receiver_id=customer.id,
        ).first()


def test_checkout_shows_party_addon_recommendations(client):
    sign_in(client)

    with client.application.app_context():
        product = Product.query.filter(
            Product.is_active.is_(True),
            Product.category.has(name="Cakes"),
        ).first()
        variant = product.variants.first()
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            Cart(
                user_id=customer.id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()

    response = client.get("/checkout")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Recommended add-ons" in html
    assert "Birthday Candle Set" in html
    assert 'name="checkout_addon_product_id"' in html
