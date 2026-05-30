import shutil
from pathlib import Path

from bootstrap_database import main as bootstrap_database_main


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static"
PUBLIC_STATIC_DIR = ROOT_DIR / "public" / "static"


def sync_static_assets():
    PUBLIC_STATIC_DIR.parent.mkdir(parents=True, exist_ok=True)
    if PUBLIC_STATIC_DIR.exists():
        shutil.rmtree(PUBLIC_STATIC_DIR)
    shutil.copytree(STATIC_DIR, PUBLIC_STATIC_DIR)


def main():
    bootstrap_database_main()
    sync_static_assets()
    print(f"Mirrored static assets to {PUBLIC_STATIC_DIR}.")


if __name__ == "__main__":
    main()
