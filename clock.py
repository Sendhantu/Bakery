from datetime import datetime, timezone


def utcnow():
    """Return a naive UTC datetime for compatibility with existing DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcdate():
    return utcnow().date()
