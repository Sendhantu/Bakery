import os

from app import PORTAL_PORTS, create_app


config_name = os.environ.get('FLASK_ENV', 'development').strip().lower() or 'development'
if config_name not in {'development', 'production', 'testing'}:
    config_name = 'default'

app = create_app(config_name, portal_role='customer')


if __name__ == '__main__':
    app.run(
        debug=config_name != 'production',
        host='127.0.0.1',
        port=PORTAL_PORTS['customer'],
        use_reloader=False,
    )
