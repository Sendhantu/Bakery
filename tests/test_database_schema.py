import sqlite3

from flask import Flask
from sqlalchemy import text

from models import db, safe_create_all


def test_safe_create_all_adds_missing_columns_to_existing_local_tables(tmp_path):
    db_path = tmp_path / "stale_bakery.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE categories (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                icon VARCHAR(50)
            )
            """
        )
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
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(120) NOT NULL,
                password VARCHAR(255),
                role VARCHAR(40)
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    app = Flask(__name__)
    app.config.update(
        ENV="development",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        safe_create_all(app)
        product_columns = {
            row["name"]
            for row in db.session.execute(text("PRAGMA table_info(products)")).mappings()
        }
        category_columns = {
            row["name"]
            for row in db.session.execute(
                text("PRAGMA table_info(categories)")
            ).mappings()
        }
        variant_columns = {
            row["name"]
            for row in db.session.execute(
                text("PRAGMA table_info(product_variants)")
            ).mappings()
        }
        user_columns = {
            row["name"]
            for row in db.session.execute(text("PRAGMA table_info(users)")).mappings()
        }

    assert {"image", "image_url"} <= category_columns
    assert {
        "image_url",
        "image_fit",
        "image_position",
        "shelf_life_hours",
        "version",
    } <= product_columns
    assert {"branch_id", "barcode", "version"} <= variant_columns
    assert {"must_change_password", "password_changed_at"} <= user_columns
