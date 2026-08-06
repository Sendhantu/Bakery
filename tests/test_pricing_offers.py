from decimal import Decimal

from models import Branch, Category, PricingRule, Product, ProductVariant, db
from services.pricing_service import PricingService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_pricing_page_shows_ai_offer_provision(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.get("/admin/pricing")

    assert response.status_code == 200
    assert b"AI Offer & Coupon Planner" in response.data
    assert b"AI not connected" in response.data
    assert b"Future AI Inputs" in response.data
    assert b"Planned AI Outputs" in response.data
    assert b'data-toggle-target="#add-pricing-rule-form"' in response.data
    assert b'id="add-pricing-rule-form" class="card mb-4 hidden"' in response.data


def test_branch_specific_pricing_rule_only_applies_to_matching_variant(admin_app):
    with admin_app.app_context():
        category = Category(name="Pricing Test Cakes", icon="C")
        branch_a = Branch(name="Pricing Branch A")
        branch_b = Branch(name="Pricing Branch B")
        product = Product(
            name="Branch Discount Cake",
            base_price=Decimal("100"),
            category=category,
            is_active=True,
        )
        db.session.add_all([category, branch_a, branch_b, product])
        db.session.flush()
        variant_a = ProductVariant(
            product_id=product.id,
            branch_id=branch_a.id,
            name="A Slice",
            price=Decimal("100"),
            stock=5,
        )
        variant_b = ProductVariant(
            product_id=product.id,
            branch_id=branch_b.id,
            name="B Slice",
            price=Decimal("100"),
            stock=5,
        )
        db.session.add_all([variant_a, variant_b])
        db.session.flush()
        db.session.add(
            PricingRule(
                name="Branch A only",
                rule_type="scheduled_discount",
                branch_id=branch_a.id,
                percent_discount=Decimal("20"),
            )
        )
        db.session.commit()

        service = PricingService()
        assert service.resolve_product_price(product, variant_a)["price"] == Decimal(
            "80.00"
        )
        assert service.resolve_product_price(product, variant_b)["price"] == Decimal(
            "100"
        )
