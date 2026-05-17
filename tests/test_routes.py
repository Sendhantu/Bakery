"""Route and portal smoke tests."""

from datetime import datetime, timedelta

from models import Coupon, Delivery, DeliveryAgent, Order, Product, ProductVariant, User, db


def sign_in(test_client, email, password):
    return test_client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=False,
    )


def create_order(app, status='PLACED', assign_delivery=False):
    with app.app_context():
        customer = User.query.filter_by(email='customer@test.com').first()
        assert customer is not None

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status=status,
            subtotal=250,
            total=250,
            address_line1='12 Test Street',
            city='Coimbatore',
            pincode='641002',
            phone='9999999999',
            delivery_slot='09:00 - 11:00',
            delivery_date=datetime.utcnow().date() + timedelta(days=1),
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
                    assigned_time=datetime.utcnow(),
                    status='ASSIGNED',
                )
            )

        db.session.commit()
        return order.id


def test_homepage(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Sweet' in response.data or b'sweet' in response.data.lower()


def test_products_page(client):
    response = client.get('/products')
    assert response.status_code == 200


def test_customer_checkout_page_loads(client):
    sign_in(client, 'customer@test.com', 'customer123')

    add_response = client.post(
        '/cart/add',
        data={'product_id': '1', 'variant_id': '1', 'quantity': '1'},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    response = client.get('/checkout')
    assert response.status_code == 200
    assert b'Checkout' in response.data
    assert b'Delivery Address' in response.data
    assert b'Use Exact Location' in response.data


def test_robots_txt(client):
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert b'User-agent' in response.data


def test_customer_login_page(client):
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert b'Welcome Back' in response.data


def test_customer_register_page_exposes_csrf_token_meta(client):
    response = client.get('/auth/register')
    assert response.status_code == 200
    assert b'name="csrf-token"' in response.data


def test_admin_login_page(admin_client):
    response = admin_client.get('/auth/login')
    assert response.status_code == 200
    assert b'Admin Sign In' in response.data
    assert b'admin@bakery.com / Admin@bakery' in response.data


def test_delivery_login_page(delivery_client):
    response = delivery_client.get('/auth/login')
    assert response.status_code == 200
    assert b'Delivery Sign In' in response.data
    assert b'delivery@bakery.com / delivery123' in response.data


def test_wrong_role_login_redirects_admin_to_admin_portal(client):
    response = sign_in(client, 'admin@bakery.com', 'Admin@bakery')
    assert response.status_code == 302
    assert response.headers['Location'] == 'http://127.0.0.1:5001/admin/'


def test_wrong_role_login_redirects_delivery_to_delivery_portal(admin_client):
    response = sign_in(admin_client, 'delivery@bakery.com', 'delivery123')
    assert response.status_code == 302
    assert response.headers['Location'] == 'http://127.0.0.1:5002/delivery/'


def test_admin_can_create_delivery_account(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    response = admin_client.post(
        '/admin/agents/add',
        data={
            'name': 'Rider One',
            'phone': '9000000001',
            'email': 'rider.one@bakery.com',
            'password': 'RiderPass1',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Delivery account created for Rider One' in response.data

    with admin_client.application.app_context():
        user = User.query.filter_by(email='rider.one@bakery.com').first()
        assert user is not None
        assert user.role == 'delivery'
        agent = DeliveryAgent.query.filter_by(user_id=user.id).first()
        assert agent is not None
        assert agent.name == 'Rider One'


def test_admin_dashboard_live_refresh_returns_fragments(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    response = admin_client.get(
        '/admin/',
        headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
        },
    )
    assert response.status_code == 200
    assert response.is_json
    assert '#admin-dashboard-live' in response.json['fragments']


def test_admin_order_detail_shows_valid_status_choices(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    order_id = create_order(admin_client.application, status='PREPARING')
    response = admin_client.get(f'/admin/orders/{order_id}')

    assert response.status_code == 200
    assert b'name="status"' in response.data
    assert b'value="PACKED"' in response.data


def test_delivery_cannot_set_packed_status(delivery_client):
    login_response = sign_in(delivery_client, 'delivery@bakery.com', 'delivery123')
    assert login_response.status_code == 302

    order_id = create_order(
        delivery_client.application,
        status='PREPARING',
        assign_delivery=True,
    )
    response = delivery_client.post(
        f'/delivery/order/{order_id}/update',
        data={'status': 'PACKED'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Invalid delivery status.' in response.data

    with delivery_client.application.app_context():
        order = Order.query.get(order_id)
        assert order is not None
        assert order.status == 'PREPARING'


def test_admin_loyalty_page_renders_config(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    response = admin_client.get('/admin/loyalty')
    assert response.status_code == 200
    assert b'100 pts = \xe2\x82\xb910 off' in response.data or b'100 pts = Rs' in response.data


def test_admin_can_toggle_coupon(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        coupon = Coupon(
            code='PHASE1',
            discount_type='flat',
            discount_value=25,
            min_order_value=0,
            max_uses=10,
        )
        db.session.add(coupon)
        db.session.commit()
        coupon_id = coupon.id

    response = admin_client.post(f'/admin/coupons/{coupon_id}/toggle', follow_redirects=True)
    assert response.status_code == 200

    with admin_client.application.app_context():
        coupon = Coupon.query.get(coupon_id)
        assert coupon is not None
        assert coupon.is_active is False


def test_inventory_page_backfills_missing_product_variant(admin_client):
    login_response = sign_in(admin_client, 'admin@bakery.com', 'Admin@bakery')
    assert login_response.status_code == 302

    with admin_client.application.app_context():
        product = Product(name='Inventory Sync Cake', base_price=399, is_active=True)
        db.session.add(product)
        db.session.commit()
        product_id = product.id
        assert ProductVariant.query.filter_by(product_id=product_id).count() == 0

    response = admin_client.get('/admin/inventory')
    assert response.status_code == 200

    with admin_client.application.app_context():
        variants = ProductVariant.query.filter_by(product_id=product_id).all()
        assert len(variants) == 1
        assert variants[0].name == 'Standard'


def test_reverse_geocode_api_validates_coordinates(client):
    sign_in(client, 'customer@test.com', 'customer123')

    response = client.get('/api/location/reverse-geocode?lat=abc&lng=123')
    assert response.status_code == 400
    assert response.is_json
    assert response.json['ok'] is False


def test_customer_can_place_pickup_order(client):
    sign_in(client, 'customer@test.com', 'customer123')

    add_response = client.post(
        '/cart/add',
        data={'product_id': '1', 'variant_id': '1', 'quantity': '1'},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    tomorrow = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        '/checkout',
        data={
            'fulfillment_type': 'PICKUP',
            'pickup_date': tomorrow,
            'pickup_slot': '09:00 - 11:00',
            'pickup_phone': '9999999999',
            'payment_method': 'COD',
            'occasion': 'Birthday',
            'special_note': 'Pickup at the front counter',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'placed successfully' in response.data

    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        assert order is not None
        assert order.fulfillment_type == 'PICKUP'
        assert order.delivery_charge == 0
        assert order.delivery_slot == '09:00 - 11:00'


def test_preorder_product_blocks_insufficient_notice_pickup(client):
    sign_in(client, 'customer@test.com', 'customer123')

    with client.application.app_context():
        product = Product(
            name='Wedding Signature Cake',
            base_price=999,
            preorder_required=True,
            minimum_notice_hours=48,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, name='Standard', price=999, stock=5)
        db.session.add(variant)
        db.session.commit()
        product_id = product.id
        variant_id = variant.id

    add_response = client.post(
        '/cart/add',
        data={'product_id': str(product_id), 'variant_id': str(variant_id), 'quantity': '1'},
        follow_redirects=False,
    )
    assert add_response.status_code in {200, 302}

    tomorrow = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        '/checkout',
        data={
            'fulfillment_type': 'PICKUP',
            'pickup_date': tomorrow,
            'pickup_slot': '09:00 - 11:00',
            'pickup_phone': '9999999999',
            'payment_method': 'COD',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'requires at least 48 hours of preorder notice' in response.data


def test_delivery_can_collect_cod_payment(delivery_client):
    login_response = sign_in(delivery_client, 'delivery@bakery.com', 'delivery123')
    assert login_response.status_code == 302

    order_id = create_order(
        delivery_client.application,
        status='OUT_FOR_DELIVERY',
        assign_delivery=True,
    )
    response = delivery_client.post(
        f'/delivery/order/{order_id}/collect-payment',
        data={'amount_received': '250', 'payment_mode': 'CASH'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'COD payment marked as collected.' in response.data

    with delivery_client.application.app_context():
        order = Order.query.get(order_id)
        assert order is not None
        assert order.payment_status == 'PAID'
