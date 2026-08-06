import os

from app import PORTAL_PORTS, create_app
from models import socketio


config_name = os.environ.get('FLASK_ENV', 'development').strip().lower() or 'development'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'default'

app = create_app(config_name, portal_role='delivery')


if __name__ == '__main__':
    socketio.run(
        app,
        debug=config_name != 'production',
        host='127.0.0.1',
        port=PORTAL_PORTS['delivery'],
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
