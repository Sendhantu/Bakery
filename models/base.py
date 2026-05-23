from flask_limiter import Limiter
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from celery import Celery
from flask_socketio import SocketIO

db = SQLAlchemy()
bcrypt = Bcrypt()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()
celery = Celery(__name__)
socketio = SocketIO()


def safe_create_all(app=None):
	"""Safely create database schema for non-production environments.

	This prevents accidental runtime schema creation in production. Tests
	and local dev may call this helper.
	"""
	from flask import current_app

	target_app = app or current_app
	env = (target_app.config.get("ENV") or "").strip().lower()
	if env == "production":
		raise RuntimeError("db.create_all() forbidden in production")
	with target_app.app_context():
		db.create_all()
