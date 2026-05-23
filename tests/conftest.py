import os
import tempfile

import pytest

from app import create_app, seed_data
from models import db


@pytest.fixture()
def app_factory(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')

    created_apps = []

    def _make(portal_role='customer'):
        app = create_app('testing', portal_role=portal_role)
        created_apps.append(app)
        with app.app_context():
            from models import safe_create_all

            safe_create_all(app)
            seed_data(app)
        return app

    yield _make

    for app in created_apps:
        with app.app_context():
            db.session.remove()
            db.drop_all()

    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture()
def app(app_factory):
    return app_factory('customer')


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_app(app_factory):
    return app_factory('admin')


@pytest.fixture()
def admin_client(admin_app):
    return admin_app.test_client()


@pytest.fixture()
def delivery_app(app_factory):
    return app_factory('delivery')


@pytest.fixture()
def delivery_client(delivery_app):
    return delivery_app.test_client()
