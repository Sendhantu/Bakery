from celery import shared_task
from bootstrap import get_container

@shared_task
def refresh_kds():
    """Placeholder Celery task to notify KDS clients to refresh via Socket.IO."""
    container = get_container()
    try:
        from realtime.events import emit_kds_refresh

        emit_kds_refresh()
        return True
    except Exception:
        return False
