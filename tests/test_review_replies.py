"""Tests for admin review reply workflow."""

from models import Product, Review, User, db


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _create_review(app, rating=5, comment="Lovely cake!"):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        product = Product.query.first()
        assert customer is not None
        assert product is not None
        review = Review(
            product_id=product.id,
            user_id=customer.id,
            rating=rating,
            comment=comment,
        )
        db.session.add(review)
        db.session.commit()
        return review.id, product.id


def test_admin_reviews_page_requires_login(admin_client):
    response = admin_client.get("/admin/reviews")
    assert response.status_code == 302


def test_admin_reviews_page_lists_reviews(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    review_id, _ = _create_review(admin_client.application, rating=4, comment="Soft and fresh.")

    response = admin_client.get("/admin/reviews")
    assert response.status_code == 200
    assert b"Customer Reviews" in response.data
    assert b"Soft and fresh." in response.data
    assert b"Generate reply draft" in response.data
    assert f'data-review-id="{review_id}"'.encode() in response.data


def test_admin_reviews_flags_low_rating(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    _create_review(admin_client.application, rating=1, comment="Disappointed.")

    response = admin_client.get("/admin/reviews")
    assert response.status_code == 200
    assert b"Needs attention" in response.data
    assert b"low rating" in response.data.lower()


def test_generate_review_draft_falls_back_without_llm(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    review_id, _ = _create_review(admin_client.application)

    response = admin_client.post(
        f"/admin/reviews/{review_id}/generate-draft",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["generation_failed"] is True
    assert payload["draft"] == ""
    assert "manually" in payload["message"].lower()


def test_admin_can_post_review_reply(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    review_id, product_id = _create_review(admin_client.application)

    response = admin_client.post(
        f"/admin/reviews/{review_id}/reply",
        data={"admin_reply": "Thank you for the kind words!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Reply posted successfully" in response.data

    with admin_client.application.app_context():
        review = db.session.get(Review, review_id)
        assert review.admin_reply == "Thank you for the kind words!"
        assert review.admin_reply_at is not None

    list_response = admin_client.get("/admin/reviews")
    assert b"Thank you for the kind words!" in list_response.data


def test_post_review_reply_rejects_empty_text(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    review_id, _ = _create_review(admin_client.application)

    response = admin_client.post(
        f"/admin/reviews/{review_id}/reply",
        data={"admin_reply": "   "},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Reply cannot be empty" in response.data

    with admin_client.application.app_context():
        review = db.session.get(Review, review_id)
        assert not review.admin_reply
