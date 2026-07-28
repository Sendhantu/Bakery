from flask_limiter import Limiter
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from celery import Celery
from flask_socketio import SocketIO
from sqlalchemy import inspect, text

db = SQLAlchemy()
bcrypt = Bcrypt()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()
celery = Celery(__name__)
socketio = SocketIO()


def _sync_missing_columns():
	"""Add model columns missing from an existing local development database."""
	inspector = inspect(db.engine)
	existing_tables = set(inspector.get_table_names())
	preparer = db.engine.dialect.identifier_preparer

	with db.engine.begin() as connection:
		for table in db.metadata.sorted_tables:
			if table.name not in existing_tables:
				continue

			existing_columns = {
				column["name"] for column in inspector.get_columns(table.name)
			}
			missing_columns = [
				column for column in table.columns if column.name not in existing_columns
			]
			for column in missing_columns:
				column_type = column.type.compile(dialect=db.engine.dialect)
				statement = (
					f"ALTER TABLE {preparer.quote(table.name)} "
					f"ADD COLUMN {preparer.quote(column.name)} {column_type}"
				)
				connection.execute(text(statement))


def safe_create_all(app=None):
	"""Safely create database schema for non-production environments.

	This prevents accidental runtime schema creation in production. Tests
	and local dev may call this helper. It also repairs older local
	databases by adding newly modeled columns that db.create_all() will not
	add to existing tables.
	"""
	from flask import current_app

	target_app = app or current_app
	env = (target_app.config.get("ENV") or "").strip().lower()
	if env == "production":
		raise RuntimeError("db.create_all() forbidden in production")
	with target_app.app_context():
		db.create_all()
		_sync_missing_columns()
