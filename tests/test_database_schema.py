import sqlite3

from sqlalchemy import text

from app import create_app
from models import db, safe_create_all


def test_safe_create_all_adds_missing_columns_to_existing_local_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "stale_bakery.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE products (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                base_price NUMERIC(10, 2) NOT NULL,
                image VARCHAR(255),
                is_active BOOLEAN
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE product_variants (
                id INTEGER NOT NULL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                price NUMERIC(10, 2) NOT NULL,
                stock INTEGER
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ENABLE_PORTAL_SIDECARS", "false")
    monkeypatch.setenv("PORTAL_LAUNCHER_CHILD", "1")

    app = create_app("development", portal_role="customer")
    with app.app_context():
        safe_create_all(app)
        product_columns = {
            row["name"]
            for row in db.session.execute(text("PRAGMA table_info(products)")).mappings()
        }
        variant_columns = {
            row["name"]
            for row in db.session.execute(
                text("PRAGMA table_info(product_variants)")
            ).mappings()
        }

    assert {"image_url", "shelf_life_hours", "version"} <= product_columns
    assert {"branch_id", "barcode", "version"} <= variant_columns
