# 🎂 SweetCrumbs Bakery — Full-Stack Web Application

A complete Bakery Management & E-Commerce platform built with **Flask + MySQL**.

## Independent Flask Apps

This repository now includes three independent launchers for the bakery platform:

- `customer_app/` runs the customer storefront on `http://127.0.0.1:5000`
- `admin_app/` runs the admin operations dashboard on `http://127.0.0.1:5001`
- `delivery_app/` runs the delivery staff panel on `http://127.0.0.1:5002`

Each one has its own:

- `app.py`
- `requirements.txt`
- `.env`

The launchers are intentionally thin wrappers around the shared production code in the root app. They each boot the same backend, but with separate portal roles, ports, and session cookies. The customer, admin, and delivery UIs still use the existing shared frontend in root `templates/` and `static/`.

All three connect to the same centralized database and can be started independently:

```bash
cd customer_app && python app.py
cd admin_app && python app.py
cd delivery_app && python app.py
```

For local development, the provided `.env` files point all three apps at the same SQLite file: `../bakery_portals_shared.db`.
For production, update each `.env` to the same MySQL URI, for example:

```env
DATABASE_URL=mysql+pymysql://root:password@localhost/bakery_central
```

## Render Customer Deployment With Local Admin

This repo now includes a Render Blueprint in [`render.yaml`](render.yaml) that deploys only the customer portal plus a managed Render Postgres database.

- The Render customer service uses the database's internal connection string automatically.
- `python scripts/bootstrap_database.py` runs as the Render `preDeployCommand` to create tables and seed the shared catalog/users before the app starts.
- Registration and other production POST actions now work with CSRF enabled because the shared base template exposes the CSRF token used by the existing frontend JavaScript.

If you want your locally running admin portal to see customer orders from the deployed website:

1. Deploy the Blueprint from this repo on Render.
2. Open the Render Postgres database's `Connect` menu and copy the `External Database URL`.
3. Paste that URL into `admin_app/.env` as `DATABASE_URL=...`.
4. Start your local admin app with `cd admin_app && python app.py`.

After that, new customer registrations and orders created on the Render website will be stored in the shared Render database, and your laptop's admin portal will read the same data.

## Mobile Frontend

The shared frontend has been tuned for smaller screens:

- improved mobile navbar layout and tap targets
- better hero, card, cart, checkout, admin, and delivery spacing
- horizontal-safe category scrollers and table wrappers
- full-width action rows on narrow screens
- phone-friendly form input sizing to reduce zoom issues

These improvements apply automatically to the customer, admin, and delivery portals because they all use the same root `templates/` and `static/css/main.css`.

## GitHub Setup

This project is now GitHub-ready for source hosting and automation:

- `.github/workflows/ci.yml` runs formatting and tests
- `.github/workflows/docker-publish.yml` builds the Docker image and publishes it to GitHub Container Registry on pushes to `main` or `master`
- `runtime.txt` pins the Python runtime for common PaaS deployments from GitHub

Important:

- GitHub Pages cannot host this app because it is a dynamic Flask + MySQL application.
- Use GitHub to store the code and run Actions, then deploy from GitHub to Render, Railway, a VPS, or another Python host.
- The Docker image published by Actions is designed for that deployment flow.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.9+
- MySQL 8.0+
- pip

---

### 2. Create MySQL Database & Tables

Open your MySQL client and run:

```bash
mysql -u root -p < schema.sql
```

Or paste the contents of `schema.sql` into MySQL Workbench / phpMyAdmin.

This creates the `bakery_db` database with all 20 tables and seed coupons.

The product catalog is now stored in MySQL and seeded from `data/products.json`. Run `python scripts/seed_products.py` after you have created the database to populate `categories`, `products`, and `product_variants`.

---

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set your MySQL password (if you use MySQL):

```
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost/bakery_db
SECRET_KEY=your-long-random-secret-key
```

If your local MySQL root password is `Sendhan@2005`, use:

```
DATABASE_URL=mysql+pymysql://root:Sendhan@2005@localhost/bakery_db
```

> In production, `SECRET_KEY` must be a strong random value. The app will refuse to start with the default key in production.

**MySQL (default fallback):** When `DATABASE_URL` is unset, the app now falls back to `MYSQL_DATABASE_URL`, and otherwise uses `mysql+pymysql://root:Sendhan@2005@localhost/bakery`.

If you prefer a local SQLite fallback for quick development, set `DATABASE_URL` explicitly to a `sqlite:///...` URI.

---

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```
> For the local AI layer, set `LLM_MODEL_PATH` in your environment to a local Llama/Mistral model file before starting the app.
>
> Example:
> ```bash
> export LLM_MODEL_PATH=/path/to/mistral-7b.gguf
> ```
---

### 5. Run the Application

```bash
python app.py
```

This will:
- Create all database tables (if not already done)
- Insert demo users, products, and coupons
- Start the Flask dev server at **http://localhost:5000**

---

## 🔑 Demo Login Credentials

| Role     | Email                   | Password     |
|----------|-------------------------|--------------|
| Admin    | admin@bakery.com        | Admin@bakery |
| Customer | customer@test.com       | customer123  |
| Delivery | delivery@bakery.com     | delivery123  |

---

## 🗂 Project Structure

```
bakery/
├── app.py                  # App factory, seed data, entry point
├── config.py               # Configuration classes
├── models.py               # SQLAlchemy ORM models (20 tables)
├── schema.sql              # Pure MySQL schema (run this first)
├── requirements.txt
├── .env.example
│
├── routes/
│   ├── auth.py             # Login, Register, Profile, Logout
│   ├── customer.py         # Shop, Cart, Checkout, Orders, Chat...
│   ├── admin.py            # Full admin panel
│   ├── delivery.py         # Delivery staff dashboard
│   └── api.py              # AJAX endpoints (coupon, search, etc.)
│
├── static/
│   ├── css/main.css        # Full responsive stylesheet
│   ├── js/main.js          # Charts, interactivity, cart logic
│   └── images/products/    # Product images go here
│
└── templates/
    ├── base.html            # Main layout with navbar/footer
    ├── auth/               login, register, profile
    ├── customer/           home, products, cart, checkout, orders...
    ├── admin/              dashboard, products, orders, analytics...
    └── delivery/           dashboard, order detail, history
```

---

## ✨ Features

### Customer
- Browse products with search, filters (category, price, egg/eggless, occasion)
- Product detail with variants (0.5kg, 1kg, 2kg), reviews & ratings
- Cart, Wishlist, Checkout with time-slot booking
- Order tracking: PLACED → PREPARING → PACKED → OUT_FOR_DELIVERY → DELIVERED
- Order cancellation (within 2 minutes), reorder, modification requests
- Address change (max 2 changes, before dispatch)
- Coupon codes, Membership discounts (10–15%)
- Chat with bakery, printable invoice, notifications

### Admin
- Full dashboard with revenue + order charts
- Product & category management with image upload
- Inventory management with low-stock alerts
- Order management with status updates & delivery assignment
- Modification request approval/rejection with price adjustment
- Customer insights with login history
- Chat dashboard (respond to customer messages)
- Analytics: revenue, top products, peak hours, order status breakdown
- Coupon & delivery agent management

### Delivery Staff
- View assigned orders with full delivery details
- Update order status (Packed → Out for Delivery → Delivered)
- Delivery history log

---

## 🗄 Database Schema

This app stores data in a relational database. If `DATABASE_URL` is set, it will use that database (MySQL is the expected production backend). Otherwise it falls back to a local SQLite file at `bakery.db`.

The full MySQL schema is defined in `schema.sql`, while the ORM models are defined in `models/`.

Product catalog data is now persisted in MySQL using `data/products.json` as the seed source. The relevant tables for products are:
- `categories` — product categories and icons
- `products` — main catalog metadata and pricing
- `product_variants` — variant sizes/options and stock levels

### Tables and main purpose

| Table | Key fields | Purpose |
|---|---|---|
| `users` | `id`, `name`, `email`, `role`, `is_active` | Stores all users and login credentials for customers, admins, and delivery staff. |
| `login_history` | `user_id`, `login_time`, `ip_address`, `status` | Tracks login attempts and access events. |
| `categories` | `name`, `icon` | Stores product categories and category icons. |
| `products` | `name`, `base_price`, `category_id`, `is_featured`, `occasion_tags` | Main product catalog with descriptions, pricing, and display flags. |
| `product_variants` | `product_id`, `name`, `price`, `stock` | Variant pricing and inventory for product sizes/options. |
| `cart` | `user_id`, `product_id`, `variant_id`, `quantity` | Temporary shopping cart contents for customers. |
| `wishlist` | `user_id`, `product_id` | Customer saved products for later. |
| `saved_addresses` | `user_id`, `label`, `address_line1`, `city`, `pincode` | Stored delivery addresses and defaults. |
| `orders` | `order_number`, `user_id`, `status`, `total`, `delivery_date`, `payment_status` | Placed orders with delivery, payment, and coupon details. |
| `order_items` | `order_id`, `product_id`, `variant_id`, `quantity`, `subtotal` | Items and pricing details for each order. |
| `address_changes` | `order_id`, `old_address`, `new_address`, `changed_by` | History of order address updates. |
| `modification_requests` | `order_id`, `user_id`, `status`, `price_diff` | Customer requests for order edits. |
| `payments` | `order_id`, `amount`, `status`, `transaction_id` | Payment status for orders. |
| `payment_links` | `token`, `user_id`, `order_id`, `status` | Generated payment link records for UPI/card flows. |
| `refunds` | `order_id`, `amount`, `status` | Refund tracking for cancelled/returned orders. |
| `coupons` | `code`, `discount_type`, `discount_value`, `valid_until`, `used_count` | Promotion codes and validation rules. |
| `subscriptions` | `user_id`, `plan`, `discount_pct`, `start_date`, `end_date` | Customer membership plans and discounts. |
| `reviews` | `product_id`, `user_id`, `rating`, `comment` | Customer product reviews and ratings. |
| `messages` | `sender_id`, `receiver_id`, `order_id`, `content`, `is_read` | In-app messaging between users and staff. |
| `notifications` | `user_id`, `title`, `message`, `is_read` | User notifications and alerts. |
| `delivery_agents` | `user_id`, `name`, `phone`, `availability` | Delivery staff profiles and availability state. |
| `deliveries` | `order_id`, `agent_id`, `status`, `delivered_time` | Order delivery assignment and status history. |
| `raw_materials` | `name`, `stock`, `reorder_level`, `cost_per_unit` | Inventory for bakery ingredients. |
| `product_materials` | `product_id`, `raw_material_id`, `quantity_required` | Links products to raw material recipes. |

---

## 🖼 Adding Product Images

Place product images in `static/images/products/`.  
Filename should match the `image` field in the products table.  
If no image found, an Unsplash placeholder is used automatically.

---

## 🧪 Tests

```bash
pytest
```

Uses a temporary SQLite database and the `testing` config (see `tests/conftest.py`).

A GitHub Actions workflow also runs `pytest` and `black --check` on every push.

---

## 📦 Production Notes

1. Change `SECRET_KEY` to a strong random value
2. Set `FLASK_ENV=production` in `.env`
3. The app exposes `/healthz` for platform health checks
4. Use a production WSGI server (Gunicorn, uWSGI)
5. Configure MySQL with proper user permissions (not root)
6. Set up a reverse proxy (Nginx/Apache)
7. Enable `USE_PROXY_FIX=true` when behind a trusted proxy
8. Set `RATE_LIMIT_STORAGE_URI` for production rate limiting (for example, `redis://user:pass@host:6379/0`)
9. Serve the app over HTTPS and verify security headers are set
