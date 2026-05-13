"""Compatibility shim for legacy imports.

The application factory now lives in /app.py. Re-export it here so any
older imports keep working without maintaining two setup paths.
"""

from app import create_app, login_manager, seed_data

try:  # Optional legacy exports
    from app import csrf  # type: ignore
except Exception:  # pragma: no cover - compatibility fallback
    csrf = None

try:
    from app import mail  # type: ignore
except Exception:  # pragma: no cover - compatibility fallback
    mail = None

__all__ = ['create_app', 'csrf', 'login_manager', 'mail', 'seed_data']
