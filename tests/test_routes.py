"""Route and portal smoke tests."""

from models import DeliveryAgent, User


def sign_in(test_client, email, password):
    return test_client.post(
        '/auth/login',
        data={'email': email, 'password': password},
        follow_redirects=False,
    )


def test_homepage(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Sweet' in response.data or b'sweet' in response.data.lower()


def test_products_page(client):
    response = client.get('/products')
    assert response.status_code == 200


def test_robots_txt(client):
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert b'User-agent' in response.data


def test_customer_login_page(client):
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert b'Welcome Back' in response.data


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
    assert response.headers['Location'] == 'http://127.0.0.1:5002/admin/'


def test_wrong_role_login_redirects_delivery_to_delivery_portal(admin_client):
    response = sign_in(admin_client, 'delivery@bakery.com', 'delivery123')
    assert response.status_code == 302
    assert response.headers['Location'] == 'http://127.0.0.1:5003/delivery/'


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
