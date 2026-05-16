import os
import gevent.monkey
gevent.monkey.patch_all()

from app import create_app

config_name = os.environ.get('FLASK_ENV', 'production').strip().lower() or 'production'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'production'

app = create_app(config_name, portal_role="customer")