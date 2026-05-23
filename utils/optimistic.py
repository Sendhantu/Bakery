from exceptions import ConflictError


def assert_version(entity, expected_version, entity_name=None):
    """Raise ConflictError if entity.version is greater than expected_version.

    If expected_version is None, do nothing.
    """
    if expected_version is None:
        return
    try:
        current = int(getattr(entity, "version", 0) or 0)
    except Exception:
        current = 0
    if current > int(expected_version):
        raise ConflictError(f"Version conflict for {entity_name or entity.__class__.__name__}")
