import os

if (os.environ.get("SOCKETIO_ASYNC_MODE") or "gevent").strip().lower() == "gevent":
    try:
        import gevent.monkey

        gevent.monkey.patch_all()
    except ImportError:  # pragma: no cover
        pass

from app import create_app

config_name = os.environ.get('FLASK_ENV', 'production').strip().lower() or 'production'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'production'

app = create_app(config_name, portal_role="customer")
