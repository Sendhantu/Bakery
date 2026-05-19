-- SweetCrumbs TiDB bootstrap
-- Upload this file to a fresh TiDB database, or run it from the TiDB SQL editor.
-- Default database name: bakerydb
SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS bakerydb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bakerydb;
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS loyalty_ledger;
DROP TABLE IF EXISTS email_log;
DROP TABLE IF EXISTS production_batches;
DROP TABLE IF EXISTS production_plans;
DROP TABLE IF EXISTS branches;
DROP TABLE IF EXISTS suppliers;
DROP TABLE IF EXISTS deliveries;
DROP TABLE IF EXISTS delivery_agents;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS payment_links;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS modification_requests;
DROP TABLE IF EXISTS address_changes;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS saved_addresses;
DROP TABLE IF EXISTS wishlist;
DROP TABLE IF EXISTS cart;
DROP TABLE IF EXISTS product_materials;
DROP TABLE IF EXISTS raw_materials;
DROP TABLE IF EXISTS product_variants;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS login_history;
DROP TABLE IF EXISTS users;
SET FOREIGN_KEY_CHECKS = 1;


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

INSERT INTO users (id, name, email, phone, password, role, permissions, is_active, avatar, oauth_id, oauth_provider) VALUES
  (1, 'Baker Admin', 'admin@bakery.com', '9999999999', '$2b$12$7/8cxTgcmJZ7elOkQmG3nucJ/lKy9ieDMgvvcSOKOjJ4DXCHnwAk.', 'admin', '[]', 1, 'default.png', NULL, NULL),
  (2, 'Delivery Staff', 'delivery@bakery.com', '8888888888', '$2b$12$YqJzSBjzxdfmITNeOjVhcekGV/qZplfOUhTLlKwUZzeCbAOsxmSNq', 'delivery', '[]', 1, 'default.png', NULL, NULL),
  (3, 'Test Customer', 'customer@test.com', '7777777777', '$2b$12$rChooTQ5Nd.9q.xhcCoqLuovO.4D1U770TedOSq9LFLojVPNn3SeC', 'customer', '[]', 1, 'default.png', NULL, NULL);

INSERT INTO categories (id, name, icon) VALUES
  (1, 'Cakes', '🎂'),
  (2, 'Pastries', '🥐'),
  (3, 'Cookies', '🍪'),
  (4, 'Breads', '🍞'),
  (5, 'Cupcakes', '🧁'),
  (6, 'Pies', '🥧');

INSERT INTO products (id, name, description, ingredients, preparation, base_price, image, category_id, is_eggless, is_active, is_featured, preorder_required, minimum_notice_hours, occasion_tags) VALUES
  (1, 'Classic Chocolate Cake', 'A rich, moist chocolate cake layered with silky ganache and topped with chocolate shavings.', 'Dark chocolate, butter, eggs, flour, sugar, cocoa powder, heavy cream', 'Baked fresh daily. Takes 2-3 hours preparation time.', 599, 'https://images.unsplash.com/photo-1548865164-1f50430ddd6f?auto=format&fit=crop&w=1200&q=80', 1, 0, 1, 1, 0, 24, 'birthday,anniversary'),
  (2, 'Red Velvet Cake', 'Velvety red sponge with cream cheese frosting. A timeless classic.', 'Red velvet mix, cream cheese, vanilla, butter, sugar', 'Baked to order. Ready in 3 hours.', 649, 'https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=1200&q=80', 1, 0, 1, 1, 0, 24, 'birthday,valentines'),
  (3, 'Eggless Vanilla Sponge', 'Light and fluffy vanilla sponge, completely egg-free. Perfect for all.', 'Flour, milk, vanilla extract, baking powder, vegetable oil, sugar', 'Prepared fresh for every order.', 549, 'https://images.unsplash.com/photo-1568051243857-068aa3ea934d?auto=format&fit=crop&w=1200&q=80', 1, 1, 1, 1, 0, 24, 'birthday,celebration'),
  (4, 'Black Forest Cake', 'German-style cake with cherries, whipped cream and chocolate sponge.', 'Chocolate sponge, whipped cream, cherries, kirsch, chocolate shavings', 'Assembled fresh on order day.', 699, 'https://images.unsplash.com/photo-1620490448382-d2f51a08596f?auto=format&fit=crop&w=1200&q=80', 1, 0, 1, 0, 0, 24, 'birthday,anniversary,wedding'),
  (5, 'Lemon Drizzle Cake', 'Zesty lemon cake with a light drizzle glaze and fresh lemon zest.', 'Flour, butter, eggs, lemon zest, sugar, yogurt', 'Baked fresh with a citrus glaze finish.', 620, 'https://images.unsplash.com/photo-1527515637465-ec7f1a35f75f?auto=format&fit=crop&w=1200&q=80', 1, 0, 1, 0, 0, 24, 'birthday,summer,celebration'),
  (6, 'Eggless Carrot Cake', 'Spiced carrot cake topped with creamy frosting — completely egg-free and moist.', 'Flour, carrots, vegetable oil, brown sugar, cinnamon, walnuts', 'Slow-baked for a moist texture and fresh flavour.', 580, 'https://images.unsplash.com/photo-1499636136210-6f4ee915583e?auto=format&fit=crop&w=1200&q=80', 1, 1, 1, 0, 0, 24, 'birthday,eggless,celebration'),
  (7, 'Butter Croissant', 'Flaky, buttery croissant with a golden crust and soft layered interior.', 'All-purpose flour, butter, yeast, milk, sugar, salt', 'Laminated dough, takes 8 hours of cold rest.', 80, 'https://images.unsplash.com/photo-1758797957671-20943209f1f5?auto=format&fit=crop&w=1200&q=80', 2, 0, 1, 0, 0, 24, ''),
  (8, 'Raspberry Almond Tart', 'Buttery tart shell filled with almond cream and topped with fresh raspberries.', 'Flour, butter, almonds, cream, raspberries, sugar', 'Baked fresh with seasonal berries.', 270, 'https://images.unsplash.com/photo-1505253214876-1283c1adf04c?auto=format&fit=crop&w=1200&q=80', 2, 0, 1, 0, 0, 24, 'gift,party'),
  (9, 'Espresso Brownie', 'Rich chocolate brownie infused with espresso and topped with crunchy nuts.', 'Dark chocolate, butter, eggs, sugar, espresso powder, walnuts', 'Baked fresh and served warm for the best taste.', 180, 'https://images.unsplash.com/photo-1505253214876-1283c1adf04c?auto=format&fit=crop&w=1200&q=80', 2, 0, 1, 0, 0, 24, 'coffee,after-meal'),
  (10, 'Classic Apple Pie', 'Warm apple pie with cinnamon-spiced filling and a flaky golden crust.', 'Apples, flour, butter, sugar, cinnamon, nutmeg', 'Made fresh and served with a crunchy top layer.', 320, 'https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=1200&q=80', 6, 0, 1, 0, 0, 24, 'dessert,party'),
  (11, 'Chocolate Pecan Pie', 'Decadent pie with chocolate ganache and toasted pecans in a buttery crust.', 'Flour, butter, chocolate, pecans, sugar, eggs', 'Baked fresh to order with crunchy nut topping.', 350, 'https://images.unsplash.com/photo-1517976487492-5750f3195933?auto=format&fit=crop&w=1200&q=80', 6, 0, 1, 0, 0, 24, 'gift,celebration'),
  (12, 'Choco Chip Cookies', 'Crispy on the outside, chewy on the inside, loaded with chocolate chips.', 'Flour, butter, brown sugar, chocolate chips, vanilla, baking soda', 'Baked fresh in small batches.', 150, 'https://images.unsplash.com/photo-1639678114429-a915fdb55000?auto=format&fit=crop&w=1200&q=80', 3, 0, 1, 1, 0, 24, ''),
  (13, 'Pistachio Macaron Box', 'Six delicate pistachio macarons with a crisp shell and creamy filling.', 'Almond flour, sugar, pistachio paste, egg whites', 'Made fresh and packaged carefully for gifting.', 320, 'https://images.unsplash.com/photo-1543930694-31a42efb9dff?auto=format&fit=crop&w=1200&q=80', 3, 0, 1, 0, 0, 24, 'gift,wedding,party'),
  (14, 'Masala Chai Cookies', 'Spiced tea cookies with cardamom, ginger and warm Indian masala flavours.', 'Flour, butter, sugar, cardamom, ginger, tea leaves', 'Baked fresh in small batches for authentic taste.', 130, 'https://images.unsplash.com/photo-1499636136210-6f4ee915583e?auto=format&fit=crop&w=1200&q=80', 3, 0, 1, 0, 0, 24, 'tea time,midnight snack'),
  (15, 'Sourdough Bread', 'Naturally fermented sourdough with a crispy crust and tangy flavor.', 'Whole wheat flour, sourdough starter, water, salt', '24-hour fermentation process for best flavor.', 220, 'https://images.unsplash.com/photo-1562099870-a3c3f2f3b44d?auto=format&fit=crop&w=1200&q=80', 4, 1, 1, 0, 0, 24, ''),
  (16, 'Black Sesame Baguette', 'Crunchy artisan baguette studded with black sesame seeds and baked to a golden crust.', 'Flour, yeast, sesame seeds, water, salt', 'Made fresh daily with a long fermentation process.', 140, 'https://images.unsplash.com/photo-1525755662778-989d0524087e?auto=format&fit=crop&w=1200&q=80', 4, 1, 1, 0, 0, 24, 'breakfast,brunch'),
  (17, 'Garlic Herb Focaccia', 'Thick, fluffy focaccia topped with rosemary, garlic, and a drizzle of olive oil.', 'Flour, yeast, olive oil, rosemary, garlic, salt', 'Hand-pressed and baked until golden.', 180, 'https://images.unsplash.com/photo-1601924638867-3e3aa9f1b237?auto=format&fit=crop&w=1200&q=80', 4, 1, 1, 0, 0, 24, 'brunch,share'),
  (18, 'Cinnamon Swirl Bread', 'Soft, spiced bread with a buttery cinnamon swirl and sugar glaze.', 'Flour, butter, cinnamon, sugar, yeast, milk', 'Rolled and baked fresh every morning.', 210, 'https://images.unsplash.com/photo-1512058564366-c9e9bbf5ac37?auto=format&fit=crop&w=1200&q=80', 4, 0, 1, 0, 0, 24, 'breakfast,tea time'),
  (19, 'Multigrain Whole Wheat Loaf', 'Nutty whole wheat loaf loaded with seeds, oats, and a hearty texture.', 'Whole wheat flour, seeds, oats, honey, yeast, salt', 'Slow-proofed for a rich, nutty flavour.', 190, 'https://images.unsplash.com/photo-1523049673857-eb18f1d7b578?auto=format&fit=crop&w=1200&q=80', 4, 1, 1, 0, 0, 24, 'breakfast,healthy');

INSERT INTO product_variants (id, product_id, name, price, stock, sku) VALUES
  (1, 1, '0.5 kg', 599, 20, NULL),
  (2, 1, '1 kg', 999, 15, NULL),
  (3, 1, '2 kg', 1799, 8, NULL),
  (4, 2, '0.5 kg', 649, 18, NULL),
  (5, 2, '1 kg', 1099, 12, NULL),
  (6, 2, '2 kg', 1899, 6, NULL),
  (7, 3, '0.5 kg', 549, 25, NULL),
  (8, 3, '1 kg', 949, 20, NULL),
  (9, 4, '0.5 kg', 699, 10, NULL),
  (10, 4, '1 kg', 1199, 8, NULL),
  (11, 4, '2 kg', 2099, 4, NULL),
  (12, 5, '0.5 kg', 620, 12, NULL),
  (13, 5, '1 kg', 1050, 9, NULL),
  (14, 6, '0.5 kg', 580, 15, NULL),
  (15, 6, '1 kg', 980, 10, NULL),
  (16, 7, 'Single', 80, 50, NULL),
  (17, 7, 'Box of 6', 450, 30, NULL),
  (18, 8, 'Single', 270, 20, NULL),
  (19, 9, 'Single', 180, 30, NULL),
  (20, 9, 'Box of 4', 680, 20, NULL),
  (21, 10, 'Single', 320, 18, NULL),
  (22, 11, 'Single', 350, 16, NULL),
  (23, 12, '6 pieces', 150, 40, NULL),
  (24, 12, '12 pieces', 280, 30, NULL),
  (25, 12, '24 pieces', 520, 20, NULL),
  (26, 13, '6 pieces', 320, 25, NULL),
  (27, 13, '12 pieces', 600, 18, NULL),
  (28, 14, '6 pieces', 130, 35, NULL),
  (29, 14, '12 pieces', 240, 25, NULL),
  (30, 15, 'Small (400g)', 220, 15, NULL),
  (31, 15, 'Large (800g)', 390, 10, NULL),
  (32, 16, 'Single', 140, 20, NULL),
  (33, 17, 'Single', 180, 18, NULL),
  (34, 18, 'Single', 210, 18, NULL),
  (35, 19, 'Single', 190, 16, NULL);

INSERT INTO coupons (id, code, discount_type, discount_value, min_order_value, max_uses, used_count, valid_from, valid_until, is_active) VALUES
  (1, 'WELCOME10', 'percentage', 10.00, 300.00, 500, 0, NOW(), DATE_ADD(NOW(), INTERVAL 365 DAY), 1),
  (2, 'FLAT50', 'flat', 50.00, 500.00, 200, 0, NOW(), DATE_ADD(NOW(), INTERVAL 365 DAY), 1),
  (3, 'SAVE15', 'percentage', 15.00, 800.00, 100, 0, NOW(), DATE_ADD(NOW(), INTERVAL 180 DAY), 1);

INSERT INTO raw_materials (id, name, unit, stock, reorder_level, cost_per_unit, supplier, notes, is_active) VALUES
  (1, 'All-Purpose Flour', 'kg', 40, 8, 62, NULL, NULL, 1),
  (2, 'Butter', 'kg', 18, 4, 540, NULL, NULL, 1),
  (3, 'Sugar', 'kg', 30, 6, 48, NULL, NULL, 1),
  (4, 'Dark Chocolate', 'kg', 16, 4, 760, NULL, NULL, 1),
  (5, 'Heavy Cream', 'litre', 12, 3, 220, NULL, NULL, 1),
  (6, 'Cream Cheese', 'kg', 9, 2, 410, NULL, NULL, 1),
  (7, 'Vanilla Extract', 'litre', 4, 1, 980, NULL, NULL, 1),
  (8, 'Cherries', 'kg', 10, 2, 260, NULL, NULL, 1),
  (9, 'Yeast', 'kg', 5, 1, 180, NULL, NULL, 1),
  (10, 'Chocolate Chips', 'kg', 8, 2, 420, NULL, NULL, 1);

INSERT INTO product_materials (id, product_id, raw_material_id, quantity_required) VALUES
  (1, 1, 1, 0.35),
  (2, 1, 2, 0.18),
  (3, 1, 3, 0.22),
  (4, 1, 4, 0.20),
  (5, 1, 5, 0.15),
  (6, 2, 1, 0.32),
  (7, 2, 2, 0.16),
  (8, 2, 3, 0.20),
  (9, 2, 6, 0.18),
  (10, 2, 7, 0.03),
  (11, 3, 1, 0.28),
  (12, 3, 3, 0.19),
  (13, 3, 2, 0.12),
  (14, 3, 7, 0.02),
  (15, 3, 5, 0.08),
  (16, 7, 1, 0.12),
  (17, 7, 2, 0.08),
  (18, 7, 9, 0.01),
  (19, 7, 3, 0.02),
  (20, 12, 1, 0.10),
  (21, 12, 2, 0.06),
  (22, 12, 3, 0.05),
  (23, 12, 10, 0.07),
  (24, 4, 1, 0.34),
  (25, 4, 2, 0.16),
  (26, 4, 3, 0.20),
  (27, 4, 5, 0.18),
  (28, 4, 8, 0.10),
  (29, 4, 4, 0.12);

INSERT INTO delivery_agents (id, user_id, name, phone, availability) VALUES (1, 2, 'Delivery Staff', '8888888888', 1);

-- End of TiDB bootstrap file