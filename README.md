# 🎂 SweetCrumbs Bakery — Full-Stack Web Application

A complete Bakery Management & E-Commerce platform built with **Flask + MySQL**.

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

**SQLite (default):** If you leave `DATABASE_URL` unset, the app uses a local **`bakery.db`** SQLite file in the project directory—no MySQL install required for quick local runs. Use MySQL for production or when you need the full `schema.sql` workflow.

---

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

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

## 🗄 Database Tables (20)

`users` · `login_history` · `categories` · `products` · `product_variants` ·
`cart` · `wishlist` · `orders` · `order_items` · `address_changes` ·
`modification_requests` · `payments` · `refunds` · `coupons` · `subscriptions` ·
`reviews` · `messages` · `notifications` · `delivery_agents` · `deliveries`

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

---

## 📦 Production Notes

1. Change `SECRET_KEY` to a strong random value
2. Set `FLASK_ENV=production` in `.env`
3. Use a production WSGI server (Gunicorn, uWSGI)
4. Configure MySQL with proper user permissions (not root)
5. Set up a reverse proxy (Nginx/Apache)
