import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app, initialize_database  # noqa: E402


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    config_name = os.environ.get("FLASK_ENV", "production").strip().lower() or "production"
    portal_role = (os.environ.get("PORTAL_ROLE") or "customer").strip().lower() or "customer"
    seed = env_flag("BOOTSTRAP_SEED_DATA", default=False)

    app = create_app(config_name, portal_role=portal_role)
    initialize_database(app, seed=seed)
    print(
        f"Database bootstrap complete for portal_role={portal_role}, "
        f"seed_data={'enabled' if seed else 'disabled'}."
    )


if __name__ == "__main__":
    main()
