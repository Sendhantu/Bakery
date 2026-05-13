import os

from app import create_app


config_name = os.environ.get('FLASK_ENV', 'development').strip().lower() or 'development'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'default'

app = create_app(config_name, portal_role=os.environ.get('PORTAL_ROLE', 'customer'))
