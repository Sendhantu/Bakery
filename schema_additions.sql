-- ─────────────────────────────────────────────────────────────
--  SWEETCRUMBS — SCHEMA ADDITIONS (run after existing schema.sql)
--  Adds: loyalty_ledger, email_log, loyalty_discount column on orders
-- ─────────────────────────────────────────────────────────────

USE bakery_db;

-- ─────────────────────────────────────────────────────────────
-- LOYALTY LEDGER
-- Double-entry: positive = earned, negative = redeemed/adjusted
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loyalty_ledger (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT          NOT NULL,
    order_id   INT          NULL,
    points     INT          NOT NULL,
    reason     VARCHAR(100) NOT NULL DEFAULT 'order_earned',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME     NULL,
    FOREIGN KEY (user_id)  REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
    INDEX idx_loyalty_user    (user_id),
    INDEX idx_loyalty_order   (order_id),
    INDEX idx_loyalty_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- EMAIL LOG
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_log (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    to_email   VARCHAR(120) NOT NULL,
    subject    VARCHAR(200),
    body_key   VARCHAR(50),
    status     VARCHAR(20)  DEFAULT 'sent',
    error      TEXT,
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_log_to (to_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ─────────────────────────────────────────────────────────────
-- ORDERS: add loyalty_discount column
-- ─────────────────────────────────────────────────────────────
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS loyalty_discount DECIMAL(10,2) DEFAULT 0
    AFTER discount;
