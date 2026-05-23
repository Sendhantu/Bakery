import os

from app import create_app
from models import celery

import tasks  # noqa: F401

config_name = os.environ.get("FLASK_ENV", "development").strip().lower() or "development"
portal_role = (os.environ.get("PORTAL_ROLE") or "customer").strip().lower() or "customer"

flask_app = create_app(config_name, portal_role=portal_role)
celery_app = celery
try:
	# Ensure Celery structured logging is configured in worker processes
	from infrastructure.logging import configure_celery_logging

	configure_celery_logging()
except Exception:
	pass
