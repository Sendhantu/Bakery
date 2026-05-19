import json
import os
from pathlib import Path

from flask_bcrypt import Bcrypt


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "tidb_bootstrap.sql"
PRODUCTS_PATH = ROOT_DIR / "data" / "products.json"
DATABASE_NAME = os.environ.get("TIDB_BOOTSTRAP_DB_NAME", "bakerydb").strip() or "bakerydb"

PASSWORDS = {
    "admin@bakery.com": "Admin@bakery",
    "delivery@bakery.com": "delivery123",
    "customer@test.com": "customer123",
}

CATEGORIES = [
    ("Cakes", "🎂"),
    ("Pastries", "🥐"),
    ("Cookies", "🍪"),
    ("Breads", "🍞"),
    ("Cupcakes", "🧁"),
    ("Pies", "🥧"),
]

RAW_MATERIALS = [
    ("All-Purpose Flour", "kg", 40, 8, 62),
    ("Butter", "kg", 18, 4, 540),
    ("Sugar", "kg", 30, 6, 48),
    ("Dark Chocolate", "kg", 16, 4, 760),
    ("Heavy Cream", "litre", 12, 3, 220),
    ("Cream Cheese", "kg", 9, 2, 410),
    ("Vanilla Extract", "litre", 4, 1, 980),
    ("Cherries", "kg", 10, 2, 260),
    ("Yeast", "kg", 5, 1, 180),
    ("Chocolate Chips", "kg", 8, 2, 420),
]

RECIPE_MAP = {
    "Classic Chocolate Cake": {
        "All-Purpose Flour": "0.35",
        "Butter": "0.18",
        "Sugar": "0.22",
        "Dark Chocolate": "0.20",
        "Heavy Cream": "0.15",
    },
    "Red Velvet Cake": {
        "All-Purpose Flour": "0.32",
        "Butter": "0.16",
        "Sugar": "0.20",
        "Cream Cheese": "0.18",
        "Vanilla Extract": "0.03",
    },
    "Eggless Vanilla Sponge": {
        "All-Purpose Flour": "0.28",
        "Sugar": "0.19",
        "Butter": "0.12",
        "Vanilla Extract": "0.02",
        "Heavy Cream": "0.08",
    },
    "Butter Croissant": {
        "All-Purpose Flour": "0.12",
        "Butter": "0.08",
        "Yeast": "0.01",
        "Sugar": "0.02",
    },
    "Choco Chip Cookies": {
        "All-Purpose Flour": "0.10",
        "Butter": "0.06",
        "Sugar": "0.05",
        "Chocolate Chips": "0.07",
    },
    "Black Forest Cake": {
        "All-Purpose Flour": "0.34",
        "Butter": "0.16",
        "Sugar": "0.20",
        "Heavy Cream": "0.18",
        "Cherries": "0.10",
        "Dark Chocolate": "0.12",
    },
}


def sql_string(value):
    if value is None:
        return "NULL"
    escaped = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def sql_bool(value):
    return "1" if value else "0"


def sql_decimal(value):
    return str(value)


def load_products():
    with PRODUCTS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_password_hashes():
    bcrypt = Bcrypt()
    return {
        email: bcrypt.generate_password_hash(password).decode("utf-8")
        for email, password in PASSWORDS.items()
    }


def write_users(lines, password_hashes):
    users = [
        (
            1,
            "Baker Admin",
            "admin@bakery.com",
            "9999999999",
            password_hashes["admin@bakery.com"],
            "admin",
        ),
        (
            2,
            "Delivery Staff",
            "delivery@bakery.com",
            "8888888888",
            password_hashes["delivery@bakery.com"],
            "delivery",
        ),
        (
            3,
            "Test Customer",
            "customer@test.com",
            "7777777777",
            password_hashes["customer@test.com"],
            "customer",
        ),
    ]

    lines.append(
        "INSERT INTO users "
        "(id, name, email, phone, password, role, permissions, is_active, avatar, oauth_id, oauth_provider) VALUES"
    )
    value_lines = []
    for user_id, name, email, phone, password_hash, role in users:
        value_lines.append(
            f"  ({user_id}, {sql_string(name)}, {sql_string(email)}, {sql_string(phone)}, "
            f"{sql_string(password_hash)}, {sql_string(role)}, '[]', 1, 'default.png', NULL, NULL)"
        )
    lines.append(",\n".join(value_lines) + ";\n")


def write_categories(lines):
    lines.append("INSERT INTO categories (id, name, icon) VALUES")
    category_lines = [
        f"  ({index}, {sql_string(name)}, {sql_string(icon)})"
        for index, (name, icon) in enumerate(CATEGORIES, start=1)
    ]
    lines.append(",\n".join(category_lines) + ";\n")


def write_products_and_variants(lines):
    products = load_products()
    category_ids = {name: index for index, (name, _) in enumerate(CATEGORIES, start=1)}
    product_ids = {}
    variant_rows = []

    lines.append(
        "INSERT INTO products "
        "(id, name, description, ingredients, preparation, base_price, image, category_id, "
        "is_eggless, is_active, is_featured, preorder_required, minimum_notice_hours, occasion_tags) VALUES"
    )
    product_rows = []
    variant_id = 1
    for product_id, product in enumerate(products, start=1):
        product_ids[product["name"]] = product_id
        product_rows.append(
            f"  ({product_id}, {sql_string(product['name'])}, {sql_string(product.get('description'))}, "
            f"{sql_string(product.get('ingredients'))}, {sql_string(product.get('preparation'))}, "
            f"{sql_decimal(product.get('base_price', 0))}, {sql_string(product.get('image'))}, "
            f"{category_ids[product.get('category', 'Cakes')]}, {sql_bool(product.get('is_eggless', False))}, "
            f"{sql_bool(product.get('is_active', True))}, {sql_bool(product.get('is_featured', False))}, "
            f"0, 24, {sql_string(product.get('occasion_tags', ''))})"
        )

        for variant in product.get("variants", []):
            variant_rows.append(
                f"  ({variant_id}, {product_id}, {sql_string(variant.get('name', 'Default'))}, "
                f"{sql_decimal(variant.get('price', 0))}, {int(variant.get('stock', 0))}, NULL)"
            )
            variant_id += 1

    lines.append(",\n".join(product_rows) + ";\n")
    lines.append(
        "INSERT INTO product_variants (id, product_id, name, price, stock, sku) VALUES"
    )
    lines.append(",\n".join(variant_rows) + ";\n")

    return product_ids


def write_coupons(lines):
    lines.append(
        "INSERT INTO coupons "
        "(id, code, discount_type, discount_value, min_order_value, max_uses, used_count, valid_from, valid_until, is_active) VALUES"
    )
    lines.append(
        "  (1, 'WELCOME10', 'percentage', 10.00, 300.00, 500, 0, NOW(), DATE_ADD(NOW(), INTERVAL 365 DAY), 1),\n"
        "  (2, 'FLAT50', 'flat', 50.00, 500.00, 200, 0, NOW(), DATE_ADD(NOW(), INTERVAL 365 DAY), 1),\n"
        "  (3, 'SAVE15', 'percentage', 15.00, 800.00, 100, 0, NOW(), DATE_ADD(NOW(), INTERVAL 180 DAY), 1);\n"
    )


def write_raw_materials(lines):
    lines.append(
        "INSERT INTO raw_materials "
        "(id, name, unit, stock, reorder_level, cost_per_unit, supplier, notes, is_active) VALUES"
    )
    rows = []
    for index, (name, unit, stock, reorder_level, cost) in enumerate(
        RAW_MATERIALS, start=1
    ):
        rows.append(
            f"  ({index}, {sql_string(name)}, {sql_string(unit)}, {stock}, {reorder_level}, {cost}, NULL, NULL, 1)"
        )
    lines.append(",\n".join(rows) + ";\n")


def write_recipe_map(lines, product_ids):
    raw_material_ids = {
        name: index for index, (name, *_rest) in enumerate(RAW_MATERIALS, start=1)
    }
    rows = []
    recipe_id = 1
    for product_name, recipe in RECIPE_MAP.items():
        for material_name, quantity in recipe.items():
            rows.append(
                f"  ({recipe_id}, {product_ids[product_name]}, {raw_material_ids[material_name]}, {quantity})"
            )
            recipe_id += 1

    if rows:
        lines.append(
            "INSERT INTO product_materials (id, product_id, raw_material_id, quantity_required) VALUES"
        )
        lines.append(",\n".join(rows) + ";\n")


def write_delivery_seed(lines):
    lines.append(
        "INSERT INTO delivery_agents (id, user_id, name, phone, availability) VALUES "
        "(1, 2, 'Delivery Staff', '8888888888', 1);\n"
    )


def main():
    password_hashes = build_password_hashes()
    lines = [
        "-- SweetCrumbs TiDB bootstrap",
        "-- Upload this file to a fresh TiDB database, or run it from the TiDB SQL editor.",
        f"-- Default database name: {DATABASE_NAME}",
        "SET NAMES utf8mb4;",
        f"CREATE DATABASE IF NOT EXISTS {DATABASE_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"USE {DATABASE_NAME};",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "DROP TABLE IF EXISTS loyalty_ledger;",
        "DROP TABLE IF EXISTS email_log;",
        "DROP TABLE IF EXISTS production_batches;",
        "DROP TABLE IF EXISTS production_plans;",
        "DROP TABLE IF EXISTS branches;",
        "DROP TABLE IF EXISTS suppliers;",
        "DROP TABLE IF EXISTS deliveries;",
        "DROP TABLE IF EXISTS delivery_agents;",
        "DROP TABLE IF EXISTS notifications;",
        "DROP TABLE IF EXISTS messages;",
        "DROP TABLE IF EXISTS reviews;",
        "DROP TABLE IF EXISTS subscriptions;",
        "DROP TABLE IF EXISTS coupons;",
        "DROP TABLE IF EXISTS refunds;",
        "DROP TABLE IF EXISTS payment_links;",
        "DROP TABLE IF EXISTS payments;",
        "DROP TABLE IF EXISTS modification_requests;",
        "DROP TABLE IF EXISTS address_changes;",
        "DROP TABLE IF EXISTS order_items;",
        "DROP TABLE IF EXISTS orders;",
        "DROP TABLE IF EXISTS saved_addresses;",
        "DROP TABLE IF EXISTS wishlist;",
        "DROP TABLE IF EXISTS cart;",
        "DROP TABLE IF EXISTS product_materials;",
        "DROP TABLE IF EXISTS raw_materials;",
        "DROP TABLE IF EXISTS product_variants;",
        "DROP TABLE IF EXISTS products;",
        "DROP TABLE IF EXISTS categories;",
        "DROP TABLE IF EXISTS login_history;",
        "DROP TABLE IF EXISTS users;",
        "SET FOREIGN_KEY_CHECKS = 1;",
        "",
        """
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(20),
    password VARCHAR(255),
    role ENUM('customer','admin','delivery') DEFAULT 'customer',
    permissions TEXT,
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    avatar VARCHAR(255) DEFAULT 'default.png',
    oauth_id VARCHAR(100) UNIQUE,
    oauth_provider VARCHAR(50),
    INDEX idx_users_email (email),
    INDEX idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE login_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(50),
    device VARCHAR(200),
    status VARCHAR(20) DEFAULT 'success',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_lh_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    icon VARCHAR(50) DEFAULT '🎂'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    ingredients TEXT,
    preparation TEXT,
    base_price DECIMAL(10,2) NOT NULL,
    image VARCHAR(255) DEFAULT 'default-product.jpg',
    category_id INT,
    is_eggless TINYINT(1) DEFAULT 0,
    is_active TINYINT(1) DEFAULT 1,
    is_featured TINYINT(1) DEFAULT 0,
    preorder_required TINYINT(1) DEFAULT 0,
    minimum_notice_hours INT DEFAULT 24,
    occasion_tags VARCHAR(300),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    INDEX idx_products_category (category_id),
    INDEX idx_products_active (is_active),
    INDEX idx_products_featured (is_featured),
    INDEX idx_products_name (name),
    INDEX idx_product_active_category (is_active, category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product_variants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INT DEFAULT 0,
    sku VARCHAR(100),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    INDEX idx_pv_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE raw_materials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    unit VARCHAR(30) NOT NULL DEFAULT 'kg',
    stock DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    reorder_level DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    cost_per_unit DECIMAL(10,2) DEFAULT 0.00,
    supplier VARCHAR(120),
    notes TEXT,
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_raw_materials_name (name),
    INDEX idx_raw_materials_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE product_materials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    raw_material_id INT NOT NULL,
    quantity_required DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (raw_material_id) REFERENCES raw_materials(id) ON DELETE CASCADE,
    UNIQUE KEY uq_product_material (product_id, raw_material_id),
    INDEX idx_product_material_product (product_id),
    INDEX idx_product_material_raw (raw_material_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE cart (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    variant_id INT,
    quantity INT DEFAULT 1,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE SET NULL,
    UNIQUE KEY uq_cart_user_variant (user_id, product_id, variant_id),
    INDEX idx_cart_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE wishlist (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY uq_wish_user_product (user_id, product_id),
    INDEX idx_wishlist_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE saved_addresses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    label VARCHAR(80) NOT NULL DEFAULT 'Saved Address',
    address_line1 VARCHAR(255) NOT NULL,
    address_line2 VARCHAR(255),
    city VARCHAR(100) NOT NULL,
    pincode VARCHAR(10) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    latitude DOUBLE,
    longitude DOUBLE,
    is_default TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_saved_addresses_user (user_id),
    INDEX idx_saved_addresses_default (user_id, is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_number VARCHAR(20) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    status VARCHAR(30) DEFAULT 'PLACED',
    subtotal DECIMAL(10,2) DEFAULT 0.00,
    discount DECIMAL(10,2) DEFAULT 0.00,
    loyalty_discount DECIMAL(10,2) DEFAULT 0.00,
    delivery_charge DECIMAL(10,2) DEFAULT 0.00,
    total DECIMAL(10,2) DEFAULT 0.00,
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    pincode VARCHAR(10),
    phone VARCHAR(20),
    fulfillment_type VARCHAR(20) DEFAULT 'DELIVERY',
    delivery_latitude DOUBLE,
    delivery_longitude DOUBLE,
    delivery_slot VARCHAR(50),
    delivery_date DATE,
    special_note TEXT,
    occasion VARCHAR(100),
    payment_method VARCHAR(50) DEFAULT 'COD',
    payment_status VARCHAR(30) DEFAULT 'PENDING',
    coupon_code VARCHAR(50),
    placed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_locked TINYINT(1) DEFAULT 0,
    address_changes INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_orders_user (user_id),
    INDEX idx_orders_status (status),
    INDEX idx_orders_placed (placed_at),
    INDEX idx_order_user_status_placed (user_id, status, placed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    variant_id INT,
    product_name VARCHAR(200),
    variant_name VARCHAR(100),
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE SET NULL,
    INDEX idx_oi_order (order_id),
    INDEX idx_oi_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE address_changes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    old_address TEXT,
    new_address TEXT,
    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    changed_by INT,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE modification_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    user_id INT NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'PENDING',
    price_diff DECIMAL(10,2) DEFAULT 0.00,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_mr_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL UNIQUE,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(30) DEFAULT 'PENDING',
    transaction_id VARCHAR(100),
    method VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE payment_links (
    id INT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    order_id INT,
    purpose VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'UPI',
    status VARCHAR(30) DEFAULT 'PENDING',
    subscription_plan VARCHAR(20),
    subscription_discount_pct DECIMAL(5,2),
    subscription_duration_days INT,
    success_url VARCHAR(255),
    cancel_url VARCHAR(255),
    gateway_reference VARCHAR(100),
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_payment_links_user (user_id),
    INDEX idx_payment_links_order (order_id),
    INDEX idx_payment_links_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE refunds (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    reason VARCHAR(255),
    status VARCHAR(30) DEFAULT 'PENDING',
    `timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_refunds_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE coupons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    discount_type VARCHAR(20) DEFAULT 'percentage',
    discount_value DECIMAL(10,2) NOT NULL,
    min_order_value DECIMAL(10,2) DEFAULT 0.00,
    max_uses INT DEFAULT 100,
    used_count INT DEFAULT 0,
    valid_from DATETIME,
    valid_until DATETIME,
    is_active TINYINT(1) DEFAULT 1,
    INDEX idx_coupons_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE subscriptions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    plan VARCHAR(20) DEFAULT 'monthly',
    discount_pct DECIMAL(5,2) DEFAULT 10.00,
    start_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    end_date DATETIME,
    is_active TINYINT(1) DEFAULT 1,
    price_paid DECIMAL(10,2),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_subscriptions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    user_id INT NOT NULL,
    rating INT NOT NULL,
    comment TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uq_review_user_product (user_id, product_id),
    INDEX idx_reviews_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sender_id INT NOT NULL,
    receiver_id INT NOT NULL,
    order_id INT,
    content TEXT NOT NULL,
    is_read TINYINT(1) DEFAULT 0,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
    INDEX idx_msg_sender (sender_id),
    INDEX idx_msg_receiver (receiver_id),
    INDEX idx_msg_read (receiver_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(200),
    message TEXT,
    type VARCHAR(50),
    is_read TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    link VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_notif_user (user_id),
    INDEX idx_notif_read (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE delivery_agents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    availability TINYINT(1) DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE deliveries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL UNIQUE,
    agent_id INT,
    assigned_time DATETIME,
    delivered_time DATETIME,
    notes TEXT,
    status VARCHAR(30) DEFAULT 'ASSIGNED',
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES delivery_agents(id) ON DELETE SET NULL,
    INDEX idx_del_agent (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE suppliers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    contact_name VARCHAR(120),
    email VARCHAR(120),
    phone VARCHAR(30),
    address TEXT,
    payment_terms VARCHAR(200),
    notes TEXT,
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE branches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    manager_name VARCHAR(120),
    phone VARCHAR(30),
    address TEXT,
    is_active TINYINT(1) DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE production_plans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    branch_id INT,
    planned_date DATETIME NOT NULL,
    quantity INT NOT NULL DEFAULT 0,
    status VARCHAR(30) DEFAULT 'Scheduled',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE production_batches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_code VARCHAR(120) NOT NULL UNIQUE,
    product_id INT NOT NULL,
    branch_id INT,
    produced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expiry_date DATETIME,
    quantity INT NOT NULL DEFAULT 0,
    waste_percentage DECIMAL(5,2) DEFAULT 0.00,
    status VARCHAR(30) DEFAULT 'Produced',
    notes TEXT,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE loyalty_ledger (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    order_id INT NULL,
    points INT NOT NULL,
    reason VARCHAR(100) NOT NULL DEFAULT 'order_earned',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
    INDEX idx_loyalty_user (user_id),
    INDEX idx_loyalty_order (order_id),
    INDEX idx_loyalty_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE email_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    to_email VARCHAR(120) NOT NULL,
    subject VARCHAR(200),
    body_key VARCHAR(50),
    status VARCHAR(20) DEFAULT 'sent',
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_log_to (to_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""
    ]

    write_users(lines, password_hashes)
    write_categories(lines)
    product_ids = write_products_and_variants(lines)
    write_coupons(lines)
    write_raw_materials(lines)
    write_recipe_map(lines, product_ids)
    write_delivery_seed(lines)
    lines.append("-- End of TiDB bootstrap file")

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
