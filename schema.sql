-- ============================================================
--  SWEET CRUMBS BAKERY — Full MySQL Schema
--  Run this file FIRST to create all tables.
--  Then run the Flask app with seed_data() to populate demo data.
-- ============================================================

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS bakery_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE bakery_db;

-- ─────────────────────────────────────────────────────────────
-- 1. USERS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)  NOT NULL,
    email       VARCHAR(120)  NOT NULL UNIQUE,
    phone       VARCHAR(20),
    password    VARCHAR(255)  NOT NULL,
    role        ENUM('customer','admin','delivery') DEFAULT 'customer',
    is_active   TINYINT(1)    DEFAULT 1,
    avatar      VARCHAR(255)  DEFAULT 'default.png',
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_email (email),
    INDEX idx_users_role  (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 2. LOGIN HISTORY
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS login_history (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT          NOT NULL,
    login_time  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    ip_address  VARCHAR(50),
    device      VARCHAR(200),
    status      VARCHAR(20)  DEFAULT 'success',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_lh_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 3. CATEGORIES
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id    INT AUTO_INCREMENT PRIMARY KEY,
    name  VARCHAR(100) NOT NULL UNIQUE,
    icon  VARCHAR(50)  DEFAULT '🎂'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 4. PRODUCTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(200)   NOT NULL,
    description    TEXT,
    ingredients    TEXT,
    preparation    TEXT,
    base_price     DECIMAL(10,2)  NOT NULL,
    image          VARCHAR(255)   DEFAULT 'default-product.jpg',
    category_id    INT,
    is_eggless     TINYINT(1)     DEFAULT 0,
    is_active      TINYINT(1)     DEFAULT 1,
    is_featured    TINYINT(1)     DEFAULT 0,
    occasion_tags  VARCHAR(300),
    created_at     DATETIME       DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    INDEX idx_products_category  (category_id),
    INDEX idx_products_active    (is_active),
    INDEX idx_products_featured  (is_featured),
    INDEX idx_products_name      (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 5. PRODUCT VARIANTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_variants (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    product_id  INT            NOT NULL,
    name        VARCHAR(100)   NOT NULL,
    price       DECIMAL(10,2)  NOT NULL,
    stock       INT            DEFAULT 0,
    sku         VARCHAR(100),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    INDEX idx_pv_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 6. CART
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cart (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT  NOT NULL,
    product_id  INT  NOT NULL,
    variant_id  INT,
    quantity    INT  DEFAULT 1,
    added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)    REFERENCES users(id)            ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)         ON DELETE CASCADE,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE SET NULL,
    UNIQUE KEY uq_cart_user_variant (user_id, product_id, variant_id),
    INDEX idx_cart_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 7. WISHLIST
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wishlist (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT  NOT NULL,
    product_id  INT  NOT NULL,
    added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY uq_wish_user_product (user_id, product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 8. SAVED ADDRESSES
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS saved_addresses (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT            NOT NULL,
    label          VARCHAR(80)    NOT NULL DEFAULT 'Saved Address',
    address_line1  VARCHAR(255)   NOT NULL,
    address_line2  VARCHAR(255),
    city           VARCHAR(100)   NOT NULL,
    pincode        VARCHAR(10)    NOT NULL,
    phone          VARCHAR(20)    NOT NULL,
    latitude       DECIMAL(10,7),
    longitude      DECIMAL(10,7),
    is_default     TINYINT(1)     DEFAULT 0,
    created_at     DATETIME       DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_saved_addresses_user (user_id),
    INDEX idx_saved_addresses_default (user_id, is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 9. ORDERS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    order_number     VARCHAR(20)    NOT NULL UNIQUE,
    user_id          INT            NOT NULL,
    status           VARCHAR(30)    DEFAULT 'PLACED',
    subtotal         DECIMAL(10,2)  DEFAULT 0.00,
    discount         DECIMAL(10,2)  DEFAULT 0.00,
    delivery_charge  DECIMAL(10,2)  DEFAULT 0.00,
    total            DECIMAL(10,2)  DEFAULT 0.00,
    -- Address
    address_line1    VARCHAR(255),
    address_line2    VARCHAR(255),
    city             VARCHAR(100),
    pincode          VARCHAR(10),
    phone            VARCHAR(20),
    delivery_latitude DECIMAL(10,7),
    delivery_longitude DECIMAL(10,7),
    -- Delivery schedule
    delivery_slot    VARCHAR(50),
    delivery_date    DATE,
    special_note     TEXT,
    occasion         VARCHAR(100),
    -- Payment
    payment_method   VARCHAR(50)    DEFAULT 'COD',
    payment_status   VARCHAR(30)    DEFAULT 'PENDING',
    coupon_code      VARCHAR(50),
    -- Meta
    placed_at        DATETIME       DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_locked        TINYINT(1)     DEFAULT 0,
    address_changes  INT            DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_orders_user   (user_id),
    INDEX idx_orders_status (status),
    INDEX idx_orders_placed (placed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 10. ORDER ITEMS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    order_id      INT            NOT NULL,
    product_id    INT            NOT NULL,
    variant_id    INT,
    product_name  VARCHAR(200),
    variant_name  VARCHAR(100),
    quantity      INT            NOT NULL,
    unit_price    DECIMAL(10,2)  NOT NULL,
    subtotal      DECIMAL(10,2)  NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders(id)           ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)         ON DELETE RESTRICT,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE SET NULL,
    INDEX idx_oi_order   (order_id),
    INDEX idx_oi_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 11. ADDRESS CHANGES (history log)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS address_changes (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    order_id     INT  NOT NULL,
    old_address  TEXT,
    new_address  TEXT,
    changed_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    changed_by   INT,
    FOREIGN KEY (order_id)   REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (changed_by) REFERENCES users(id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 12. MODIFICATION REQUESTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS modification_requests (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    order_id     INT            NOT NULL,
    user_id      INT            NOT NULL,
    description  TEXT,
    status       VARCHAR(20)    DEFAULT 'PENDING',
    price_diff   DECIMAL(10,2)  DEFAULT 0.00,
    created_at   DATETIME       DEFAULT CURRENT_TIMESTAMP,
    resolved_at  DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE RESTRICT,
    INDEX idx_mr_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 13. PAYMENTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    order_id        INT            NOT NULL UNIQUE,
    amount          DECIMAL(10,2)  NOT NULL,
    status          VARCHAR(30)    DEFAULT 'PENDING',
    transaction_id  VARCHAR(100),
    method          VARCHAR(50),
    created_at      DATETIME       DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_links (
    id                         INT AUTO_INCREMENT PRIMARY KEY,
    token                      VARCHAR(64)    NOT NULL UNIQUE,
    user_id                    INT            NOT NULL,
    order_id                   INT,
    purpose                    VARCHAR(30)    NOT NULL,
    title                      VARCHAR(200)   NOT NULL,
    amount                     DECIMAL(10,2)  NOT NULL,
    payment_method             VARCHAR(50)    DEFAULT 'UPI',
    status                     VARCHAR(30)    DEFAULT 'PENDING',
    subscription_plan          VARCHAR(20),
    subscription_discount_pct  DECIMAL(5,2),
    subscription_duration_days INT,
    success_url                VARCHAR(255),
    cancel_url                 VARCHAR(255),
    gateway_reference          VARCHAR(100),
    notes                      TEXT,
    created_at                 DATETIME       DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_payment_links_user (user_id),
    INDEX idx_payment_links_order (order_id),
    INDEX idx_payment_links_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 14. REFUNDS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS refunds (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    order_id   INT            NOT NULL,
    amount     DECIMAL(10,2)  NOT NULL,
    reason     VARCHAR(255),
    status     VARCHAR(30)    DEFAULT 'PENDING',
    `timestamp` DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    INDEX idx_refunds_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 15. COUPONS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS coupons (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    code             VARCHAR(50)    NOT NULL UNIQUE,
    discount_type    VARCHAR(20)    DEFAULT 'percentage',
    discount_value   DECIMAL(10,2)  NOT NULL,
    min_order_value  DECIMAL(10,2)  DEFAULT 0.00,
    max_uses         INT            DEFAULT 100,
    used_count       INT            DEFAULT 0,
    valid_from       DATETIME,
    valid_until      DATETIME,
    is_active        TINYINT(1)     DEFAULT 1,
    INDEX idx_coupons_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 16. SUBSCRIPTIONS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT            NOT NULL,
    plan          VARCHAR(20)    DEFAULT 'monthly',
    discount_pct  DECIMAL(5,2)   DEFAULT 10.00,
    start_date    DATETIME       DEFAULT CURRENT_TIMESTAMP,
    end_date      DATETIME,
    is_active     TINYINT(1)     DEFAULT 1,
    price_paid    DECIMAL(10,2),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_subscriptions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 17. REVIEWS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    product_id  INT  NOT NULL,
    user_id     INT  NOT NULL,
    rating      INT  NOT NULL,
    comment     TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE,
    UNIQUE KEY uq_review_user_product (user_id, product_id),
    INDEX idx_reviews_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 18. MESSAGES
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    sender_id    INT  NOT NULL,
    receiver_id  INT  NOT NULL,
    order_id     INT,
    content      TEXT NOT NULL,
    is_read      TINYINT(1) DEFAULT 0,
    sent_at      DATETIME   DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_id)   REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (order_id)    REFERENCES orders(id) ON DELETE SET NULL,
    INDEX idx_msg_sender   (sender_id),
    INDEX idx_msg_receiver (receiver_id),
    INDEX idx_msg_read     (receiver_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 19. NOTIFICATIONS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT          NOT NULL,
    title      VARCHAR(200),
    message    TEXT,
    type       VARCHAR(50),
    is_read    TINYINT(1)   DEFAULT 0,
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    link       VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_notif_user (user_id),
    INDEX idx_notif_read (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 20. DELIVERY AGENTS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS delivery_agents (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT,
    name          VARCHAR(100) NOT NULL,
    phone         VARCHAR(20),
    availability  TINYINT(1)   DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 21. DELIVERIES
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deliveries (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    order_id        INT  NOT NULL UNIQUE,
    agent_id        INT,
    assigned_time   DATETIME,
    delivered_time  DATETIME,
    notes           TEXT,
    status          VARCHAR(30) DEFAULT 'ASSIGNED',
    FOREIGN KEY (order_id) REFERENCES orders(id)          ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES delivery_agents(id) ON DELETE SET NULL,
    INDEX idx_del_agent (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 22. RAW MATERIALS
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_materials (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(120)   NOT NULL UNIQUE,
    unit           VARCHAR(30)    NOT NULL DEFAULT 'kg',
    stock          DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
    reorder_level  DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
    cost_per_unit  DECIMAL(10,2)  DEFAULT 0.00,
    supplier       VARCHAR(120),
    notes          TEXT,
    is_active      TINYINT(1)     DEFAULT 1,
    created_at     DATETIME       DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_raw_materials_name (name),
    INDEX idx_raw_materials_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- 23. PRODUCT MATERIALS / RECIPE MAP
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_materials (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    product_id         INT            NOT NULL,
    raw_material_id    INT            NOT NULL,
    quantity_required  DECIMAL(10,2)  NOT NULL DEFAULT 0.00,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (raw_material_id) REFERENCES raw_materials(id) ON DELETE CASCADE,
    UNIQUE KEY uq_product_material (product_id, raw_material_id),
    INDEX idx_product_material_product (product_id),
    INDEX idx_product_material_raw (raw_material_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- SEED DATA (safe to re-run — uses INSERT IGNORE)
-- ─────────────────────────────────────────────────────────────

-- Categories
INSERT IGNORE INTO categories (name, icon) VALUES
  ('Cakes',    '🎂'),
  ('Pastries', '🥐'),
  ('Cookies',  '🍪'),
  ('Breads',   '🍞'),
  ('Cupcakes', '🧁'),
  ('Pies',     '🥧');

-- Demo Users  (passwords are bcrypt hashes — seeded by Flask app.py seed_data())
-- Run `python app.py` to create + seed all demo users automatically.

-- Demo Coupons
INSERT IGNORE INTO coupons
  (code, discount_type, discount_value, min_order_value, max_uses, valid_until)
VALUES
  ('WELCOME10', 'percentage', 10.00, 300.00, 500, DATE_ADD(NOW(), INTERVAL 1 YEAR)),
  ('FLAT50',    'flat',       50.00, 500.00, 200, DATE_ADD(NOW(), INTERVAL 1 YEAR)),
  ('SAVE15',    'percentage', 15.00, 800.00, 100, DATE_ADD(NOW(), INTERVAL 6 MONTH));

-- Demo Raw Materials
INSERT IGNORE INTO raw_materials
  (name, unit, stock, reorder_level, cost_per_unit)
VALUES
  ('All-Purpose Flour', 'kg', 40.00, 8.00, 62.00),
  ('Butter', 'kg', 18.00, 4.00, 540.00),
  ('Sugar', 'kg', 30.00, 6.00, 48.00),
  ('Dark Chocolate', 'kg', 16.00, 4.00, 760.00),
  ('Heavy Cream', 'litre', 12.00, 3.00, 220.00),
  ('Cream Cheese', 'kg', 9.00, 2.00, 410.00),
  ('Vanilla Extract', 'litre', 4.00, 1.00, 980.00),
  ('Cherries', 'kg', 10.00, 2.00, 260.00),
  ('Yeast', 'kg', 5.00, 1.00, 180.00),
  ('Chocolate Chips', 'kg', 8.00, 2.00, 420.00);

-- ─────────────────────────────────────────────────────────────
-- USEFUL QUERIES FOR REFERENCE
-- ─────────────────────────────────────────────────────────────

-- Revenue summary by day:
-- SELECT DATE(placed_at) as day, COUNT(*) as orders, SUM(total) as revenue
-- FROM orders WHERE status != 'CANCELLED'
-- GROUP BY DATE(placed_at) ORDER BY day DESC;

-- Top selling products:
-- SELECT p.name, SUM(oi.quantity) as units_sold, SUM(oi.subtotal) as revenue
-- FROM order_items oi JOIN products p ON oi.product_id = p.id
-- GROUP BY p.id ORDER BY units_sold DESC LIMIT 10;

-- Low stock alert:
-- SELECT p.name, pv.name as variant, pv.stock
-- FROM product_variants pv JOIN products p ON pv.product_id = p.id
-- WHERE pv.stock <= 5 ORDER BY pv.stock ASC;
