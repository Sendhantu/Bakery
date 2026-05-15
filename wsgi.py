import os

from app import create_app


config_name = os.environ.get('FLASK_ENV', 'development').strip().lower() or 'development'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'default'

portal_role = (
    os.environ.get('PORTAL_ROLE')
    or os.environ.get('SERVICE_ROLE')
    or 'customer'
)

app = create_app(config_name, portal_role=portal_role)
