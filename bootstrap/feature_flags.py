import os


class FeatureFlagService:
    def __init__(self, flags=None):
        self._flags = dict(flags or {})

    def is_enabled(self, key, default=False):
        env_key = f"FEATURE_FLAG__{key.upper().replace('.', '__')}"
        if env_key in os.environ:
            return os.environ[env_key].strip().lower() in {"1", "true", "yes", "on"}
        return bool(self._flags.get(key, default))
