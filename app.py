import json
import os
from datetime import datetime
from decimal import Decimal

from flask import Flask, request, send_from_directory, url_for
from flask_login import LoginManager
from flask_mail import Mail
from flask_wtf import CSRFProtect

from config import config
from models import User, bcrypt, cache, db, limiter, socketio

login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
CREDENTIAL_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), 'output', 'dev_credentials.json')
STARTUP_BANNER_CACHE = set()

PORTAL_PORTS = {
    'customer': 5001,
    'admin': 5002,
    'delivery': 5003,
}

LOCAL_PORTAL_URLS = {
    role: f'http://127.0.0.1:{port}'
    for role, port in PORTAL_PORTS.items()
}

DEMO_PORTAL_CREDENTIALS = {
    'customer': {
        'email': 'customer@test.com',
        'password': 'customer123',
        'label': 'Customer Demo',
    },
    'admin': {
        'email': 'admin@bakery.com',
        'password': 'Admin@bakery',
        'label': 'Admin Default',
    },
    'delivery': {
        'email': 'delivery@bakery.com',
        'password': 'delivery123',
        'label': 'Delivery Default',
    },
}


def env_flag(name):
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def resolve_portal_role(portal_role=None):
    candidate = (portal_role or os.environ.get('PORTAL_ROLE') or '').strip().lower()
    if candidate in PORTAL_PORTS:
        return candidate
    return 'customer'


def configured_portal_url(role, config_name):
    env_key = f'{role.upper()}_PORTAL_URL'
    configured = (os.environ.get(env_key) or '').strip().rstrip('/')
    if configured:
        return configured
    if config_name != 'production':
        return LOCAL_PORTAL_URLS[role]
    return ''


def _normalize_credential_entry(role, entry, default_source='default'):
    return {
        'role': role,
        'email': entry.get('email', ''),
        'password': entry.get('password', ''),
        'label': entry.get('label') or f'{role.title()} Account',
        'source': entry.get('source', default_source),
        'updated_at': entry.get('updated_at', ''),
    }


def _ensure_credential_registry_dir():
    os.makedirs(os.path.dirname(CREDENTIAL_REGISTRY_PATH), exist_ok=True)


def load_recorded_development_credentials():
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return {}

    _ensure_credential_registry_dir()
    if not os.path.exists(CREDENTIAL_REGISTRY_PATH):
        return {}

    try:
        with open(CREDENTIAL_REGISTRY_PATH, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def save_recorded_development_credentials(payload):
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return

    _ensure_credential_registry_dir()
    with open(CREDENTIAL_REGISTRY_PATH, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def record_development_credential(role, email, password, label='', source='manual'):
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return

    email = (email or '').strip().lower()
    password = (password or '').strip()
    role = (role or 'customer').strip().lower()
    if not email or not password or role not in PORTAL_PORTS:
        return

    registry = load_recorded_development_credentials()
    registry[email] = {
        'role': role,
        'email': email,
        'password': password,
        'label': label or f'{role.title()} Account',
        'source': source,
        'updated_at': datetime.utcnow().isoformat(timespec='seconds'),
    }
    save_recorded_development_credentials(registry)


def get_available_development_credentials():
    credentials = {
        entry['email']: _normalize_credential_entry(role, entry)
        for role, entry in DEMO_PORTAL_CREDENTIALS.items()
    }

    for email, entry in load_recorded_development_credentials().items():
        role = (entry.get('role') or 'customer').strip().lower()
        if role not in PORTAL_PORTS:
            role = 'customer'
        credentials[email] = _normalize_credential_entry(role, entry, default_source='recorded')

    return sorted(
        credentials.values(),
        key=lambda item: (
            ['customer', 'admin', 'delivery'].index(item['role']) if item['role'] in {'customer', 'admin', 'delivery'} else 99,
            item['email'],
        ),
    )


def print_development_startup_banner(app):
    if app.testing or app.config.get('ENV') == 'production' or os.environ.get('PORTAL_LAUNCHER_CHILD') == '1':
        return

    cache_key = (
        app.config.get('PORTAL_ROLE', 'customer'),
        app.config.get('CUSTOMER_PORTAL_URL'),
        app.config.get('ADMIN_PORTAL_URL'),
        app.config.get('DELIVERY_PORTAL_URL'),
    )
    if cache_key in STARTUP_BANNER_CACHE:
        return

    STARTUP_BANNER_CACHE.add(cache_key)
    print('', flush=True)
    print('SweetCrumbs local portals:', flush=True)
    print(f"  Customer: {app.config.get('CUSTOMER_PORTAL_URL')}", flush=True)
    print(f"  Admin:    {app.config.get('ADMIN_PORTAL_URL')}", flush=True)
    print(f"  Delivery: {app.config.get('DELIVERY_PORTAL_URL')}", flush=True)
    print('', flush=True)
    print('Available login credentials:', flush=True)
    for entry in get_available_development_credentials():
        print(
            f"  [{entry['role'].upper():8}] {entry['email']} / {entry['password']}"
            + (f"  ({entry['label']})" if entry['label'] else ''),
            flush=True,
        )
    print('', flush=True)
    print('New customer signups and delivery password resets are also recorded here during development.', flush=True)


def create_app(config_name='default', portal_role=None):
    config_name = (config_name or 'default').strip().lower() or 'default'
    if config_name not in config:
        config_name = 'default'

    app = Flask(__name__)
    app.config.from_object(config[config_name])
    database_url = (os.environ.get('DATABASE_URL') or '').strip()
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config.setdefault('CACHE_TYPE', 'SimpleCache')
    app.config['PORTAL_ROLE'] = resolve_portal_role(portal_role)
    app.config['PORTAL_PORTS'] = PORTAL_PORTS
    app.config['SHOW_DEMO_ACCOUNTS'] = config_name != 'production'

    auto_init_override = env_flag('AUTO_INIT_DB')
    if auto_init_override is not None:
        app.config['AUTO_INIT_DB'] = auto_init_override

    for role in PORTAL_PORTS:
        app.config[f'{role.upper()}_PORTAL_URL'] = configured_portal_url(role, config_name)

    # Init extensions
    db.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)
    cache.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app, async_mode='threading', cors_allowed_origins='*')
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register Blueprints
    from routes.auth import auth_bp, oauth
    from routes.customer import customer_bp
    from routes.admin import admin_bp
    from routes.delivery import delivery_bp
    from routes.api import api_bp

    oauth.init_app(app)

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(customer_bp, url_prefix='')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(delivery_bp, url_prefix='/delivery')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    @app.route('/robots.txt')
    def robots_txt():
        return send_from_directory(app.static_folder, 'robots.txt', mimetype='text/plain')

    # Context processors
    @app.context_processor
    def inject_globals():
        from models import Category, Notification
        from flask_login import current_user

        current_portal_role = app.config.get('PORTAL_ROLE', 'customer')

        def build_parallel_login_url():
            host, _, port = request.host.partition(':')
            if host not in {'127.0.0.1', 'localhost'}:
                return None, None

            alternate_host = 'localhost' if host == '127.0.0.1' else '127.0.0.1'
            port_suffix = f':{port}' if port else ''
            return (
                f'{request.scheme}://{alternate_host}{port_suffix}{url_for("auth.login")}',
                alternate_host
            )

        def build_portal_urls():
            request_host = request.host.split(':', 1)[0].lower()
            if request_host in {'127.0.0.1', 'localhost'}:
                return {
                    role: f'{request.scheme}://{request_host}:{port}'
                    for role, port in PORTAL_PORTS.items()
                }

            current_root = f'{request.scheme}://{request.host}'
            portal_urls = {}
            for role in PORTAL_PORTS:
                configured = (app.config.get(f'{role.upper()}_PORTAL_URL') or '').rstrip('/')
                portal_urls[role] = configured or current_root
            return portal_urls

        categories = Category.query.all()
        unread_count = 0
        if current_user.is_authenticated:
            unread_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
        parallel_login_url, parallel_host = build_parallel_login_url()
        return dict(
            categories=categories,
            unread_notifs=unread_count,
            bakery_name=app.config['BAKERY_NAME'],
            site_meta_description=app.config.get('SITE_META_DESCRIPTION', ''),
            store_details=app.config['STORE_DETAILS'],
            current_portal_role=current_portal_role,
            parallel_login_url=parallel_login_url,
            parallel_host=parallel_host,
            current_year=datetime.now().year,
            portal_urls=build_portal_urls(),
            portal_demo_credentials=DEMO_PORTAL_CREDENTIALS,
            show_demo_accounts=app.config.get('SHOW_DEMO_ACCOUNTS', False),
        )

    if app.config.get('AUTO_INIT_DB'):
        with app.app_context():
            db.create_all()
            seed_data(app)
    print_development_startup_banner(app)

    return app


def seed_data(app):
    """Seed demo data"""
    with app.app_context():
        from models import User, Category, Product, ProductVariant, Coupon, DeliveryAgent, RawMaterial, ProductMaterial

        # Admin user
        admin = User.query.filter_by(email=DEMO_PORTAL_CREDENTIALS['admin']['email']).first()
        if not admin:
            admin = User(
                name='Baker Admin',
                email=DEMO_PORTAL_CREDENTIALS['admin']['email'],
                role='admin',
                phone='9999999999',
            )
            db.session.add(admin)
        admin.name = 'Baker Admin'
        admin.role = 'admin'
        admin.phone = '9999999999'
        admin.is_active = True
        admin.set_password(DEMO_PORTAL_CREDENTIALS['admin']['password'])
        record_development_credential(
            'admin',
            DEMO_PORTAL_CREDENTIALS['admin']['email'],
            DEMO_PORTAL_CREDENTIALS['admin']['password'],
            label=DEMO_PORTAL_CREDENTIALS['admin']['label'],
            source='seeded',
        )

        # Delivery user
        duser = User.query.filter_by(email=DEMO_PORTAL_CREDENTIALS['delivery']['email']).first()
        if not duser:
            duser = User(
                name='Delivery Staff',
                email=DEMO_PORTAL_CREDENTIALS['delivery']['email'],
                role='delivery',
                phone='8888888888',
            )
            db.session.add(duser)
            db.session.flush()
        duser.name = 'Delivery Staff'
        duser.role = 'delivery'
        duser.phone = '8888888888'
        duser.is_active = True
        duser.set_password(DEMO_PORTAL_CREDENTIALS['delivery']['password'])
        agent = DeliveryAgent.query.filter_by(user_id=duser.id).first()
        if not agent:
            agent = DeliveryAgent(user_id=duser.id, name='Delivery Staff', phone='8888888888')
            db.session.add(agent)
        agent.name = 'Delivery Staff'
        agent.phone = '8888888888'
        record_development_credential(
            'delivery',
            DEMO_PORTAL_CREDENTIALS['delivery']['email'],
            DEMO_PORTAL_CREDENTIALS['delivery']['password'],
            label=DEMO_PORTAL_CREDENTIALS['delivery']['label'],
            source='seeded',
        )

        # Sample customer
        cust = User.query.filter_by(email=DEMO_PORTAL_CREDENTIALS['customer']['email']).first()
        if not cust:
            cust = User(
                name='Test Customer',
                email=DEMO_PORTAL_CREDENTIALS['customer']['email'],
                role='customer',
                phone='7777777777',
            )
            db.session.add(cust)
        cust.name = 'Test Customer'
        cust.role = 'customer'
        cust.phone = '7777777777'
        cust.is_active = True
        cust.set_password(DEMO_PORTAL_CREDENTIALS['customer']['password'])
        record_development_credential(
            'customer',
            DEMO_PORTAL_CREDENTIALS['customer']['email'],
            DEMO_PORTAL_CREDENTIALS['customer']['password'],
            label=DEMO_PORTAL_CREDENTIALS['customer']['label'],
            source='seeded',
        )

        # Categories
        cats_data = [
            ('Cakes', '🎂'), ('Pastries', '🥐'), ('Cookies', '🍪'),
            ('Breads', '🍞'), ('Cupcakes', '🧁'), ('Pies', '🥧')
        ]
        for cname, icon in cats_data:
            if not Category.query.filter_by(name=cname).first():
                db.session.add(Category(name=cname, icon=icon))
        db.session.flush()

        # Products
        cake_cat = Category.query.filter_by(name='Cakes').first()
        pastry_cat = Category.query.filter_by(name='Pastries').first()
        cookie_cat = Category.query.filter_by(name='Cookies').first()
        bread_cat = Category.query.filter_by(name='Breads').first()
        cupcake_cat = Category.query.filter_by(name='Cupcakes').first()

        products_data = [
            {
                'name': 'Classic Chocolate Cake',
                'description': 'A rich, moist chocolate cake layered with silky ganache and topped with chocolate shavings.',
                'ingredients': 'Dark chocolate, butter, eggs, flour, sugar, cocoa powder, heavy cream',
                'preparation': 'Baked fresh daily. Takes 2-3 hours preparation time.',
                'base_price': 599,
                'image': 'https://images.unsplash.com/photo-1548865164-1f50430ddd6f?auto=format&fit=crop&w=1200&q=80',
                'category_id': cake_cat.id if cake_cat else 1,
                'is_eggless': False,
                'is_featured': True,
                'occasion_tags': 'birthday,anniversary',
                'variants': [('0.5 kg', 599, 20), ('1 kg', 999, 15), ('2 kg', 1799, 8)]
            },
            {
                'name': 'Red Velvet Cake',
                'description': 'Velvety red sponge with cream cheese frosting. A timeless classic.',
                'ingredients': 'Red velvet mix, cream cheese, vanilla, butter, sugar',
                'preparation': 'Baked to order. Ready in 3 hours.',
                'base_price': 649,
                'image': 'https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=1200&q=80',
                'category_id': cake_cat.id if cake_cat else 1,
                'is_eggless': False,
                'is_featured': True,
                'occasion_tags': 'birthday,valentines',
                'variants': [('0.5 kg', 649, 18), ('1 kg', 1099, 12), ('2 kg', 1899, 6)]
            },
            {
                'name': 'Eggless Vanilla Sponge',
                'description': 'Light and fluffy vanilla sponge, completely egg-free. Perfect for all.',
                'ingredients': 'Flour, milk, vanilla extract, baking powder, vegetable oil, sugar',
                'preparation': 'Prepared fresh for every order.',
                'base_price': 549,
                'image': 'https://images.unsplash.com/photo-1568051243857-068aa3ea934d?auto=format&fit=crop&w=1200&q=80',
                'category_id': cake_cat.id if cake_cat else 1,
                'is_eggless': True,
                'is_featured': True,
                'occasion_tags': 'birthday,celebration',
                'variants': [('0.5 kg', 549, 25), ('1 kg', 949, 20)]
            },
            {
                'name': 'Butter Croissant',
                'description': 'Flaky, buttery croissant with a golden crust and soft layered interior.',
                'ingredients': 'All-purpose flour, butter, yeast, milk, sugar, salt',
                'preparation': 'Laminated dough, takes 8 hours of cold rest.',
                'base_price': 80,
                'image': 'https://images.unsplash.com/photo-1758797957671-20943209f1f5?auto=format&fit=crop&w=1200&q=80',
                'category_id': pastry_cat.id if pastry_cat else 2,
                'is_eggless': False,
                'is_featured': False,
                'occasion_tags': '',
                'variants': [('Single', 80, 50), ('Box of 6', 450, 30)]
            },
            {
                'name': 'Choco Chip Cookies',
                'description': 'Crispy on the outside, chewy on the inside, loaded with chocolate chips.',
                'ingredients': 'Flour, butter, brown sugar, chocolate chips, vanilla, baking soda',
                'preparation': 'Baked fresh in small batches.',
                'base_price': 150,
                'image': 'https://images.unsplash.com/photo-1639678114429-a915fdb55000?auto=format&fit=crop&w=1200&q=80',
                'category_id': cookie_cat.id if cookie_cat else 3,
                'is_eggless': False,
                'is_featured': True,
                'occasion_tags': '',
                'variants': [('6 pieces', 150, 40), ('12 pieces', 280, 30), ('24 pieces', 520, 20)]
            },
            {
                'name': 'Sourdough Bread',
                'description': 'Naturally fermented sourdough with a crispy crust and tangy flavor.',
                'ingredients': 'Whole wheat flour, sourdough starter, water, salt',
                'preparation': '24-hour fermentation process for best flavor.',
                'base_price': 220,
                'image': 'https://images.unsplash.com/photo-1562099870-a3c3f2f3b44d?auto=format&fit=crop&w=1200&q=80',
                'category_id': bread_cat.id if bread_cat else 4,
                'is_eggless': True,
                'is_featured': False,
                'occasion_tags': '',
                'variants': [('Small (400g)', 220, 15), ('Large (800g)', 390, 10)]
            },
            {
                'name': 'Rainbow Cupcakes',
                'description': 'Colorful cupcakes with swirled frosting, perfect for celebrations.',
                'ingredients': 'Flour, eggs, butter, sugar, food colors, frosting',
                'preparation': 'Made to order for freshness.',
                'base_price': 60,
                'image': 'https://images.unsplash.com/photo-1486427944299-d1955d23e34d?auto=format&fit=crop&w=1200&q=80',
                'category_id': cupcake_cat.id if cupcake_cat else 5,
                'is_eggless': False,
                'is_featured': True,
                'occasion_tags': 'birthday,celebration,kids',
                'variants': [('Single', 60, 30), ('Box of 6', 340, 20), ('Box of 12', 650, 12)]
            },
            {
                'name': 'Black Forest Cake',
                'description': 'German-style cake with cherries, whipped cream and chocolate sponge.',
                'ingredients': 'Chocolate sponge, whipped cream, cherries, kirsch, chocolate shavings',
                'preparation': 'Assembled fresh on order day.',
                'base_price': 699,
                'image': 'https://images.unsplash.com/photo-1620490448382-d2f51a08596f?auto=format&fit=crop&w=1200&q=80',
                'category_id': cake_cat.id if cake_cat else 1,
                'is_eggless': False,
                'is_featured': False,
                'occasion_tags': 'birthday,anniversary,wedding',
                'variants': [('0.5 kg', 699, 10), ('1 kg', 1199, 8), ('2 kg', 2099, 4)]
            },
        ]

        placeholder_images = {None, '', 'default-product.jpg'}
        for pd in products_data:
            existing_product = Product.query.filter_by(name=pd['name']).first()
            product_payload = {key: value for key, value in pd.items() if key != 'variants'}

            if existing_product:
                if existing_product.image in placeholder_images:
                    existing_product.image = pd['image']
                continue

            prod = Product(**product_payload)
            db.session.add(prod)
            db.session.flush()
            for vname, vprice, vstock in pd['variants']:
                db.session.add(ProductVariant(
                    product_id=prod.id, name=vname, price=vprice, stock=vstock
                ))

        raw_materials_data = [
            ('All-Purpose Flour', 'kg', 40, 8, 62),
            ('Butter', 'kg', 18, 4, 540),
            ('Sugar', 'kg', 30, 6, 48),
            ('Dark Chocolate', 'kg', 16, 4, 760),
            ('Heavy Cream', 'litre', 12, 3, 220),
            ('Cream Cheese', 'kg', 9, 2, 410),
            ('Vanilla Extract', 'litre', 4, 1, 980),
            ('Cherries', 'kg', 10, 2, 260),
            ('Yeast', 'kg', 5, 1, 180),
            ('Chocolate Chips', 'kg', 8, 2, 420),
        ]
        for name, unit, stock, reorder_level, cost in raw_materials_data:
            if not RawMaterial.query.filter_by(name=name).first():
                db.session.add(RawMaterial(
                    name=name,
                    unit=unit,
                    stock=stock,
                    reorder_level=reorder_level,
                    cost_per_unit=cost
                ))
        db.session.flush()

        recipe_map = {
            'Classic Chocolate Cake': {
                'All-Purpose Flour': Decimal('0.35'),
                'Butter': Decimal('0.18'),
                'Sugar': Decimal('0.22'),
                'Dark Chocolate': Decimal('0.20'),
                'Heavy Cream': Decimal('0.15'),
            },
            'Red Velvet Cake': {
                'All-Purpose Flour': Decimal('0.32'),
                'Butter': Decimal('0.16'),
                'Sugar': Decimal('0.20'),
                'Cream Cheese': Decimal('0.18'),
                'Vanilla Extract': Decimal('0.03'),
            },
            'Eggless Vanilla Sponge': {
                'All-Purpose Flour': Decimal('0.28'),
                'Sugar': Decimal('0.19'),
                'Butter': Decimal('0.12'),
                'Vanilla Extract': Decimal('0.02'),
                'Heavy Cream': Decimal('0.08'),
            },
            'Butter Croissant': {
                'All-Purpose Flour': Decimal('0.12'),
                'Butter': Decimal('0.08'),
                'Yeast': Decimal('0.01'),
                'Sugar': Decimal('0.02'),
            },
            'Choco Chip Cookies': {
                'All-Purpose Flour': Decimal('0.10'),
                'Butter': Decimal('0.06'),
                'Sugar': Decimal('0.05'),
                'Chocolate Chips': Decimal('0.07'),
            },
            'Black Forest Cake': {
                'All-Purpose Flour': Decimal('0.34'),
                'Butter': Decimal('0.16'),
                'Sugar': Decimal('0.20'),
                'Heavy Cream': Decimal('0.18'),
                'Cherries': Decimal('0.10'),
                'Dark Chocolate': Decimal('0.12'),
            },
        }

        for product_name, material_requirements in recipe_map.items():
            product = Product.query.filter_by(name=product_name).first()
            if not product:
                continue

            for material_name, quantity_required in material_requirements.items():
                material = RawMaterial.query.filter_by(name=material_name).first()
                if not material:
                    continue

                existing_requirement = ProductMaterial.query.filter_by(
                    product_id=product.id,
                    raw_material_id=material.id
                ).first()
                if existing_requirement:
                    continue

                db.session.add(ProductMaterial(
                    product_id=product.id,
                    raw_material_id=material.id,
                    quantity_required=quantity_required
                ))

        # Coupons
        if not Coupon.query.filter_by(code='WELCOME10').first():
            from datetime import datetime, timedelta
            db.session.add(Coupon(
                code='WELCOME10', discount_type='percentage', discount_value=10,
                min_order_value=300, max_uses=500,
                valid_until=datetime.utcnow() + timedelta(days=365)
            ))
        if not Coupon.query.filter_by(code='FLAT50').first():
            from datetime import datetime, timedelta
            db.session.add(Coupon(
                code='FLAT50', discount_type='flat', discount_value=50,
                min_order_value=500, max_uses=200,
                valid_until=datetime.utcnow() + timedelta(days=365)
            ))

        db.session.commit()
        print("✅ Seed data inserted successfully.")


if __name__ == '__main__':
    app = create_app('development')
    with app.app_context():
        db.create_all()
        seed_data(app)
    app.run(debug=True, port=5000)
