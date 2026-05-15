import os
import sys
import importlib.util
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(Path(__file__).resolve().with_name(".env"), override=True)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite:////"):
    relative_path = database_url.removeprefix("sqlite:///")
    absolute_path = (Path(__file__).resolve().parent / relative_path).resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{absolute_path}"

ROOT_APP_PATH = ROOT_DIR / "app.py"
ROOT_APP_MODULE_NAME = "bakery_root_app_delivery"
ROOT_APP_SPEC = importlib.util.spec_from_file_location(
    ROOT_APP_MODULE_NAME, ROOT_APP_PATH
)
ROOT_APP_MODULE = importlib.util.module_from_spec(ROOT_APP_SPEC)
ROOT_APP_SPEC.loader.exec_module(ROOT_APP_MODULE)

APP_PORT = ROOT_APP_MODULE.PORTAL_PORTS["delivery"]
config_name = (
    os.environ.get("FLASK_ENV", "development").strip().lower() or "development"
)
app = ROOT_APP_MODULE.create_app(config_name, portal_role="delivery")
app.template_folder = str(ROOT_DIR / "templates")
app.static_folder = str(ROOT_DIR / "static")
if hasattr(app.jinja_loader, "searchpath"):
    app.jinja_loader.searchpath = [str(ROOT_DIR / "templates")]


if __name__ == "__main__":
    app.run(
        debug=config_name != "production",
        host="127.0.0.1",
        port=APP_PORT,
        use_reloader=False,
    )
