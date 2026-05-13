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
