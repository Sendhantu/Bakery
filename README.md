# SweetCrumbs Bakery — Production-Ready Hybrid Platform

A complete, production-grade bakery management and e-commerce platform built with Flask, featuring hybrid cloud deployment, offline-first operations, mobile delivery support, and enterprise-grade operational tooling.

## 🏗️ Architecture Overview

### Hybrid Deployment Model

This platform uses a **hybrid architecture** where only the customer-facing portal is public, while admin and delivery operations remain local and secure:

```text
PUBLIC INTERNET (Render Cloud)
├── Customer Portal → https://your-app.onrender.com
│   ├── Product catalog & shopping
│   ├── Customer checkout & orders
│   ├── Order tracking
│   └── Public storefront
│
LOCAL PRIVATE SYSTEMS (Your Laptop & Delivery Phones)
├── Admin Portal → http://127.0.0.1:5001
│   ├── Inventory management
│   ├── Order management
│   ├── Production planning
│   ├── Staff management
│   ├── Analytics dashboard
│   └── Offline-first operations
│
└── Delivery Portal → http://127.0.0.1:5002 (Mobile PWA)
    ├── Delivery assignments
    ├── Route optimization
    ├── Status updates
    ├── Offline queueing
    └── Mobile-optimized UI
│
SHARED CLOUD INFRASTRUCTURE
├── TiDB Cloud → Primary MySQL-compatible database
├── Redis → Socket.IO message queue, Celery broker, cache, rate limiting
└── Cloudinary → Product images, invoice PDFs, file storage
```

### Key Architecture Principles

- **One Flask codebase** serving all portals via `PORTAL_ROLE` environment variable
- **One TiDB database** as the single source of truth for all data
- **One Redis cluster** for real-time synchronization and background tasks
- **SQLite is NEVER production data** — only used for local offline buffering in `instance/offline/`
- **Production schema changes** via `flask db upgrade` only (see `migrations/versions/`)
- **Admin and delivery portals remain private** — never deployed to public cloud

## 🚀 Quick Start (Local Development)

### Prerequisites

- Python 3.9+
- TiDB Cloud account (or local MySQL 8.0+)
- Redis server (local or cloud)
- Cloudinary account (for image storage)

### Installation

```bash
# Clone and setup
git clone https://github.com/Sendhantu/Bakery.git
cd bakery
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your TiDB, Redis, and Cloudinary credentials
```

### Running All Portals Locally

```bash
# Option 1: Run all portals at once (development mode)
python app.py

# This starts:
# - Customer portal on http://127.0.0.1:5000
# - Admin portal on http://127.0.0.1:5001
# - Delivery portal on http://127.0.0.1:5002
```

### Running Individual Portals

```bash
# Terminal 1 — Customer Portal
cd customer_app && cp .env.example .env && python app.py

# Terminal 2 — Admin Portal (with offline sync)
cd admin_app && cp .env.example .env && python app.py

# Terminal 3 — Delivery Portal (mobile PWA)
cd delivery_app && cp .env.example .env && python app.py

# Terminal 4 — Celery Worker (for background tasks)
celery -A celery_app.celery worker --loglevel=info

# Terminal 5 — Celery Beat (for scheduled jobs)
celery -A celery_app.celery beat --loglevel=info
```

### Portal Access

| Portal   | URL                      | Purpose                          |
|----------|--------------------------|----------------------------------|
| Customer | http://127.0.0.1:5000    | Public storefront & ordering      |
| Admin    | http://127.0.0.1:5001    | Admin operations & management     |
| Delivery | http://127.0.0.1:5002    | Delivery operations (mobile PWA)  |

### Demo Credentials (Development Only)

The application displays demo credentials on startup. They are also saved to `output/dev_credentials.json`:

| Role     | Email                   | Password     |
|----------|-------------------------|--------------|
| Admin    | admin@bakery.com        | Admin@bakery |
| Customer | customer@test.com       | customer123  |
| Delivery | delivery@bakery.com     | delivery123  |

## ☁️ Render Deployment Guide

### Deployment Architecture

**IMPORTANT:** Only the customer portal is deployed to Render. Admin and delivery portals run locally on your laptop and delivery phones.

```text
Render Cloud (Public)
├── bakery-customer-portal (Web Service)
│   ├── Gunicorn + Gevent WebSocket Worker
│   ├── Customer Portal Only (PORTAL_ROLE=customer)
│   └── Health Check: /healthz
│
├── bakery-celery-worker (Worker Service)
│   ├── Background Task Processing
│   └── Email, SMS, Invoice Generation, Sync Retries
│
└── bakery-redis (Redis Service)
    ├── Socket.IO Message Queue
    ├── Celery Broker & Result Backend
    ├── Flask Cache
    └── Rate Limiting Storage

External Cloud Services (Required)
├── TiDB Cloud (Database)
├── Cloudinary (Image/File Storage)
└── Optional: Firebase (Push Notifications)
```

### Step-by-Step Render Deployment

#### 1. Prepare TiDB Cloud

1. Create a TiDB Cloud Serverless cluster
2. Create a database named `bakerydb`
3. Create a database user with strong password
4. Add your IP to the allowlist (for local admin/delivery access)
5. Add Render outbound IPs to allowlist (check Render docs for current ranges)

#### 2. Prepare Cloudinary

1. Sign up at cloudinary.com
2. Create a new cloud (or use existing)
3. Navigate to Settings → API Keys
4. Note down: Cloud name, API Key, API Secret

#### 3. Deploy to Render

```bash
# Push to GitHub
git add .
git commit -m "Production deployment"
git push origin main

# In Render dashboard:
# 1. Click "New +" → "Blueprint"
# 2. Connect your GitHub repository
# 3. Select render.yaml as the blueprint file
# 4. Review and deploy
```

#### 4. Configure Render Environment Variables

The `render.yaml` includes most configuration, but you must manually set these in the Render dashboard:

**TiDB Database (Required):**
- `DB_HOST`: Your TiDB Cloud host (e.g., `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`)
- `DB_PORT`: `4000` (already set in render.yaml)
- `DB_USER`: Your TiDB username
- `DB_PASSWORD`: Your TiDB password
- `DB_NAME`: `bakerydb`

**Cloudinary (Required):**
- `CLOUDINARY_CLOUD_NAME`: Your Cloudinary cloud name
- `CLOUDINARY_API_KEY`: Your Cloudinary API key
- `CLOUDINARY_API_SECRET`: Your Cloudinary API secret

**Optional Services:**
- `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`: For email notifications
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`: For SMS/WhatsApp
- `GOOGLE_MAPS_API_KEY`: For delivery routing
- `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`: For push notifications
- `SENTRY_DSN`: For error monitoring

**Portal URLs (for CORS):**
- `CUSTOMER_PORTAL_URL`: Your Render URL (e.g., `https://bakery-customer-portal.onrender.com`)

#### 5. Run Database Migrations

The `render.yaml` includes a pre-deploy command that runs migrations automatically:

```yaml
preDeployCommand: python scripts/bootstrap_database.py
```

This script:
1. Runs `flask db upgrade` to apply all migrations
2. Seeds initial data if `BOOTSTRAP_SEED_DATA=true`

#### 6. Verify Deployment

```bash
# Check health endpoint
curl https://your-app.onrender.com/healthz

# Expected response:
# {
#   "status": "ok",
#   "database": "ok",
#   "redis": "ok",
#   "celery": "ok",
#   "storage": "ok"
# }
```

### Render Deployment Troubleshooting

| Issue | Solution |
|-------|----------|
| **Deployment fails during build** | Check `requirements.txt` for incompatible versions |
| **Database connection error** | Verify TiDB credentials, IP allowlist, SSL settings |
| **Redis connection error** | Verify Redis URL in render.yaml is correctly linked |
| **Health check failing** | Check /healthz endpoint response, verify all services |
| **WebSocket not working** | Ensure Gevent WebSocket worker is configured in gunicorn.conf.py |
| **Static files not loading** | Check static folder structure and Cloudinary configuration |
| **Celery tasks not running** | Verify Celery worker is running and connected to Redis |
| **Migrations not applying** | Check pre-deploy command output in Render logs |

### Production Hardening on Render

The platform includes production hardening that activates automatically:

- **SQLite Forbidden:** App will refuse to start if SQLite is detected in production
- **Strong Secrets:** Weak SECRET_KEY values are rejected
- **Required Environment Variables:** App fails startup if critical vars missing
- **Secure Cookies:** SESSION_COOKIE_SECURE, REMEMBER_COOKIE_SECURE enforced
- **HTTPS Only:** Automatic redirect from HTTP to HTTPS
- **ProxyFix Enabled:** Correct handling behind Render's load balancer
- **CSP Headers:** Content Security Policy for XSS protection

## 🗄️ TiDB Cloud Setup Guide

### Why TiDB Cloud?

TiDB Cloud is a MySQL-compatible, distributed SQL database that provides:
- **Horizontal scalability** for growing order volumes
- **High availability** with automatic failover
- **MySQL compatibility** — works with existing SQLAlchemy models
- **Serverless pricing** — pay only for what you use
- **Built-in backups** and point-in-time recovery

### Step-by-Step TiDB Cloud Setup

#### 1. Create TiDB Cloud Account

1. Visit [tidbcloud.com](https://tidbcloud.com)
2. Sign up for a free account
3. Verify your email address

#### 2. Create a Serverless Cluster

1. Click "Create Cluster"
2. Choose "Serverless" (recommended for production)
3. Select a region close to your users (e.g., Singapore for Asia-Pacific)
4. Name your cluster (e.g., `bakery-production`)
5. Click "Create"

#### 3. Create Database and User

1. Once the cluster is ready, click "Connect"
2. Use the SQL editor to run:

```sql
CREATE DATABASE bakerydb;
USE bakerydb;

CREATE USER 'bakery_user'@'%' IDENTIFIED BY 'STRONG_PASSWORD_HERE';
GRANT ALL PRIVILEGES ON bakerydb.* TO 'bakery_user'@'%';
FLUSH PRIVILEGES;
```

#### 4. Configure IP Allowlist

**For Local Development:**
1. Go to Cluster Settings → Security
2. Add your public IP address
3. Or add `0.0.0.0/0` for testing (not recommended for production)

**For Render Deployment:**
1. Add Render's outbound IP ranges (check Render documentation)
2. Common ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`

#### 5. Get Connection Details

1. Click "Connect" on your cluster
2. Note down:
   - **Host:** (e.g., `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`)
   - **Port:** `4000`
   - **Username:** (e.g., `bakery_user`)
   - **Password:** (the password you set)

#### 6. Configure Environment Variables

Add these to your `.env` file or Render environment:

```bash
# TiDB Cloud Configuration
DB_HOST=gateway01.ap-southeast-1.prod.aws.tidbcloud.com
DB_PORT=4000
DB_USER=bakery_user
DB_PASSWORD=your_strong_password_here
DB_NAME=bakerydb

# SSL Configuration (Required for TiDB Cloud)
DB_SSL_CA=/etc/ssl/certs/ca-certificates.crt
DB_SSL_VERIFY_CERT=true
DB_SSL_VERIFY_IDENTITY=true
```

#### 7. Run Database Migrations

```bash
# Local development
flask db upgrade

# Or use the bootstrap script
python scripts/bootstrap_database.py
```

This will create all required tables, indexes, and relationships.

### Alternative: Import SQL Seed

For greenfield deployments, you can import the pre-generated schema:

```bash
# Generate bootstrap SQL from models
python scripts/generate_tidb_bootstrap.py > tidb_bootstrap.sql

# Import via TiDB Cloud SQL editor or command line
mysql -h <host> -P 4000 -u bakery_user -p bakerydb < tidb_bootstrap.sql
```

### Connection String Format

The application uses SQLAlchemy with PyMySQL:

```
mysql+pymysql://user:password@host:port/database
```

With SSL parameters added automatically from `DB_SSL_*` environment variables.

### Database Connection Pooling

Production configuration includes connection pooling:

```python
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,        # Test connections before use
    "pool_recycle": 280,          # Recycle connections after 280s
    "pool_size": 20,              # Base pool size
    "max_overflow": 40,           # Additional connections when needed
    "pool_timeout": 30,           # Wait timeout for connections
}
```

### TiDB Cloud Best Practices

- **Use Serverless** for variable workloads (bakery has peak/demand cycles)
- **Monitor resource usage** in TiDB Cloud dashboard
- **Set up alerts** for CPU and memory usage
- **Regular backups** are automatic, but verify restore process
- **Connection pooling** is configured — don't create too many connections

## 🔄 Redis Setup Guide

### Why Redis?

Redis is required in production for:
- **Socket.IO message queue** — enables multi-worker websocket synchronization
- **Celery broker** — background task queue
- **Celery result backend** — task result storage
- **Flask-Caching** — product, analytics, and recommendation caching
- **Rate limiting** — API rate limit storage

### Local Redis Setup

#### macOS (Homebrew)

```bash
brew install redis
brew services start redis
# Redis runs on redis://127.0.0.1:6379/0
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
# Redis runs on redis://127.0.0.1:6379/0
```

#### Windows

```bash
# Download Redis for Windows from GitHub releases
# Or use Docker:
docker run -d -p 6379:6379 redis:latest
```

### Cloud Redis Setup

#### Render Redis

The `render.yaml` automatically provisions a Redis instance:

```yaml
- name: bakery-redis
  type: redis
  plan: free
  ipAllowList: []
```

The Redis URL is automatically linked to web and worker services.

#### Upstash Redis (Alternative)

1. Sign up at [upstash.com](https://upstash.com)
2. Create a new Redis database
3. Copy the REST URL or Redis URL
4. Set `REDIS_URL` environment variable

#### Redis Cloud (Redis Labs)

1. Sign up at [redis.com](https://redis.com)
2. Create a new Redis Cloud database
3. Copy the connection string
4. Set `REDIS_URL` environment variable

### Environment Configuration

```bash
# Local development
REDIS_URL=redis://127.0.0.1:6379/0

# Render (auto-linked from render.yaml)
REDIS_URL=redis://default:password@host:port

# Upstash
REDIS_URL=redis://default:password@host:port

# Redis Cloud
REDIS_URL=rediss://:password@host:port
```

### Redis Usage in the Platform

#### Socket.IO Message Queue

```python
# config/base.py
SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE") or REDIS_URL

# app.py
socketio.init_app(
    app,
    async_mode="gevent",
    message_queue=message_queue,
)
```

This enables multi-worker Socket.IO deployments on Render.

#### Celery Broker and Backend

```python
# config/base.py
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL
```

#### Flask-Caching

```python
# config/base.py
CACHE_TYPE = "RedisCache" if REDIS_URL else "SimpleCache"
CACHE_REDIS_URL = REDIS_URL
CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes
```

#### Rate Limiting

```python
# config/base.py
RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI") or REDIS_URL
```

### Redis Health Check

The `/healthz` endpoint validates Redis connectivity:

```python
try:
    from redis import Redis
    Redis.from_url(redis_url).ping()
    redis_state = "ok"
except Exception:
    redis_state = "unhealthy"
    status_code = 503
```

### Redis Best Practices

- **Use connection pooling** — configured automatically
- **Set appropriate TTL** for cached data
- **Monitor memory usage** — Redis is in-memory
- **Use Redis Cloud for production** — better reliability and scaling
- **Backup Redis data** — if using persistence

## 📷 Cloudinary Setup Guide

### Why Cloudinary?

Cloudinary is used for all file storage in the platform:
- **Product images** — uploaded by admin, displayed to customers
- **Invoice PDFs** — generated and stored for download
- **No local storage** — files survive restarts and deployments
- **CDN delivery** — automatic global CDN for fast image loading
- **Image optimization** — automatic WebP conversion and compression

### Step-by-Step Cloudinary Setup

#### 1. Create Cloudinary Account

1. Visit [cloudinary.com](https://cloudinary.com)
2. Sign up for a free account
3. Verify your email address

#### 2. Create a Cloud (or use default)

1. Navigate to the Dashboard
2. Note your **Cloud Name** (e.g., `sweetcrumbs-bakery`)

#### 3. Get API Credentials

1. Go to Settings → API Keys
2. Note down:
   - **Cloud Name:** (from dashboard)
   - **API Key:** (32-character string)
   - **API Secret:** (32-character string)

#### 4. Configure Environment Variables

Add these to your `.env` file or Render environment:

```bash
# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
PRODUCT_IMAGE_FOLDER=sweetcrumbs/products
```

#### 5. Test Cloudinary Connection

The `/healthz` endpoint validates Cloudinary connectivity:

```python
storage_check = app.extensions["service_container"].storage_service.verify_connection()
storage_state = storage_check["status"]
```

### Cloudinary Usage in the Platform

#### Product Image Upload

```python
# services/storage_service.py
def upload_product_image(file_storage, *, filename_prefix="product"):
    public_id = f"{filename_prefix}-{os.urandom(4).hex()}"
    result = cloudinary.uploader.upload(
        file_storage,
        folder="sweetcrumbs/products",
        public_id=public_id,
        overwrite=True,
        invalidate=True,
        resource_type="image",
        format="webp",
        transformation=[
            {"quality": "auto", "fetch_format": "auto"},
        ],
    )
    return result["secure_url"]
```

#### Invoice PDF Upload

```python
def upload_bytes(payload, *, public_id, resource_type="raw", format_ext="pdf"):
    result = cloudinary.uploader.upload(
        payload,
        public_id=public_id,
        resource_type=resource_type,
        format=format_ext,
        overwrite=True,
        invalidate=True,
    )
    return {"url": result.get("secure_url"), "public_id": result.get("public_id")}
```

### Cloudinary Best Practices

- **Use folders** to organize images by type
- **Enable auto-format** for WebP conversion (smaller files)
- **Set quality to auto** for optimal compression
- **Use public IDs** that are predictable and searchable
- **Invalidate cache** after uploads to force CDN refresh
- **Monitor usage** — free tier has limits

### Cloudinary Security

- **API Secret** should never be committed to git
- **Signed URLs** can be used for private images
- **Upload presets** can restrict file types and sizes
- **Transformations** can be applied on-the-fly for resizing

## ⚙️ Celery Setup Guide

### Why Celery?

Celery handles all background and scheduled tasks:
- **Email sending** — order confirmations, notifications
- **SMS/WhatsApp sending** — delivery updates, promotions
- **Invoice generation** — PDF creation and delivery
- **Recommendation generation** — collaborative filtering updates
- **Analytics aggregation** — hourly/daily statistics
- **Inventory alerts** — low stock notifications
- **Offline sync retries** — automatic sync after reconnection
- **Subscription order generation** — recurring billing orders
- **Backup verification** — health checks on backups

### Local Celery Setup

#### Start Celery Worker

```bash
# Terminal 1 — Worker
celery -A celery_app.celery worker --loglevel=info --concurrency=2

# With beat scheduler combined (for development)
celery -A celery_app.celery worker --beat --loglevel=info
```

#### Start Celery Beat (Separate)

```bash
# Terminal 2 — Beat scheduler
celery -A celery_app.celery beat --loglevel=info
```

### Production Celery Setup (Render)

The `render.yaml` includes a Celery worker service:

```yaml
- type: worker
  name: bakery-celery-worker
  runtime: python
  startCommand: celery -A celery_app.celery worker --loglevel=info --concurrency=2
```

### Scheduled Jobs

The following tasks are scheduled in `config/base.py`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `build_inventory_forecasts` | Every 6 hours | Predict inventory needs |
| `generate_subscription_orders` | Every 15 minutes | Create recurring subscription orders |
| `retry_offline_sync_actions` | Every 60 seconds | Retry failed offline syncs |
| `capture_queue_metrics` | Every 5 minutes | Monitor Celery queue health |
| `verify_backup_health` | Every 12 hours | Verify TiDB/Cloudinary backups |
| `aggregate_analytics_snapshot` | Every 30 minutes | Aggregate sales analytics |
| `process_birthday_rewards` | Daily | Send birthday loyalty rewards |
| `send_abandoned_cart_reminders` | Every 2 hours | Send WhatsApp cart reminders |

### Celery Configuration

```python
# config/base.py
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL
CELERY_BEAT_SCHEDULE = {
    "inventory-forecasts-nightly": {
        "task": "tasks.operations.build_inventory_forecasts",
        "schedule": 60 * 60 * 6,
    },
    # ... more schedules
}
```

### Celery Health Check

The `/healthz` endpoint validates Celery connectivity:

```python
try:
    broker = app.config.get("CELERY_BROKER_URL")
    backend = app.config.get("CELERY_RESULT_BACKEND")
    if not broker or not backend:
        if app.config.get("ENV") == "production":
            raise RuntimeError("Celery broker/backend not configured")
    else:
        from redis import Redis
        Redis.from_url(broker).ping()
        registered = list(celery.tasks.keys())
        if not any(name.startswith("tasks.") for name in registered):
            celery_state = "degraded"
except Exception:
    celery_state = "unhealthy"
    status_code = 503
```

### Celery Best Practices

- **Use separate worker and beat** in production
- **Set appropriate concurrency** — 2-4 workers per CPU core
- **Monitor queue length** — long queues indicate bottlenecks
- **Use task timeouts** — prevent hanging tasks
- **Implement task retries** — with exponential backoff
- **Log task execution** — for debugging and monitoring

### Celery Troubleshooting

| Issue | Solution |
|-------|----------|
| **Tasks not executing** | Check Celery worker is running and connected to Redis |
| **Beat not scheduling** | Verify beat scheduler is running, check schedule syntax |
| **Task stuck in queue** | Check worker logs, verify task is registered |
| **Memory leaks** | Restart workers periodically, monitor memory usage |
| **Connection errors** | Verify Redis URL, check Redis connectivity |

## 📱 Offline-First Synchronization

### Why Offline-First?

Admin and delivery portals need to function during internet outages:
- **Network reliability** — bakery operations continue despite connectivity issues
- **Mobile delivery** — delivery agents work in areas with poor coverage
- **Data integrity** — no lost orders or inventory updates
- **Automatic recovery** — seamless sync when internet reconnects

### How Offline Sync Works

```text
┌─────────────────────────────────────────────────────────────┐
│ OFFLINE MODE (TiDB Unreachable)                            │
├─────────────────────────────────────────────────────────────┤
│ 1. Admin updates stock offline                             │
│ 2. Action queued to local SQLite                           │
│ 3. Local snapshot updated for UI                          │
│ 4. User sees "Offline mode" warning                        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ RECONNECT (Internet Restored)                              │
├─────────────────────────────────────────────────────────────┤
│ 1. Browser triggers sync endpoint                          │
│ 2. Celery processes queued actions                         │
│ 3. Changes pushed to TiDB                                  │
│ 4. Version conflicts detected & flagged                    │
│ 5. Customer portal reflects changes immediately            │
└─────────────────────────────────────────────────────────────┘
```

### Offline Sync Architecture

**Local Storage (SQLite):**
- Location: `instance/offline/{portal}_offline_sync.sqlite`
- Purpose: Queued actions and local snapshots only
- Never used as production database
- Enforced by `forbid_sqlite_in_production()` check

**Sync Queue:**
- Actions queued with unique `request_id`
- Includes actor_id, timestamp, entity type, payload
- Idempotent — duplicate requests rejected via audit log

**Conflict Resolution:**
- Version checking on all sync operations
- Conflicts create `sync_conflicts` entries
- Admin resolves via Admin → Offline / Sync

### Offline Sync Workflow

#### 1. Detect Offline Status

```python
# services/offline_sync_service.py
def is_online(self):
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
```

#### 2. Queue Offline Actions

```python
# routes/admin.py
offline_sync = get_container().offline_sync_service
if offline_sync.enabled and not offline_sync.is_online():
    request_id = offline_sync.queue_order_status_update_by_id(
        order_id,
        status,
        actor_id=current_user.id,
        expected_version=snapshot.get("version"),
        snapshot_payload={**snapshot, "id": order_id, "status": status},
    )
    flash(f"Offline mode: status change queued for sync ({request_id[:8]}).", "warning")
```

#### 3. Automatic Sync on Reconnect

```javascript
// templates/delivery/base_delivery.html
function _triggerOfflineSync() {
  try {
    fetch('/internal/trigger_offline_sync', { method: 'POST', credentials: 'include' }).catch(()=>{});
  } catch (e) {}
}
window.addEventListener('online', _triggerOfflineSync);
if (navigator.onLine) _triggerOfflineSync();
```

#### 4. Celery Retry Job

```python
# tasks/operations.py
@celery.task
def retry_offline_sync_actions():
    """Retry failed offline sync actions every minute"""
    # Process queued actions from local SQLite
    # Push to TiDB with conflict detection
    # Mark as completed or failed
```

### Conflict Handling

**Version Conflicts:**
- If remote record version > local version → conflict
- Creates `sync_conflicts` entry
- Admin must manually resolve

**Resolution Options:**
- Keep remote (discard local changes)
- Keep local (overwrite remote)
- Merge (manual data entry)

### Offline Sync Best Practices

- **Test offline mode** — disconnect network and verify queueing
- **Monitor sync backlog** — check Admin → Offline / Sync
- **Resolve conflicts promptly** — prevent data divergence
- **Regular backups** — of local SQLite files
- **Network awareness** — UI shows online/offline status

### Production Safety

The platform enforces strict rules:

```python
# config/utils.py
def forbid_sqlite_in_production(database_uri, env_name):
    if (env_name or "").strip().lower() == "production" and "sqlite" in (
        database_uri or ""
    ).lower():
        raise RuntimeError("SQLite forbidden in production")
```

SQLite is ONLY permitted for:
- Offline sync queue
- Local temporary cache
- Offline operation buffering

Production order/customer/product data MUST remain centralized in TiDB.

## 📲 Mobile Delivery Portal

### Why Mobile Delivery?

Delivery agents work primarily on phones:
- **Field operations** — delivery agents are always on the move
- **Touch interface** — optimized for mobile interaction
- **Offline capability** — works in areas with poor coverage
- **PWA support** — installable as native app
- **Real-time updates** — instant delivery assignment notifications

### Mobile Delivery Features

#### Responsive Design
- Touch-friendly buttons and controls
- Mobile-optimized dashboard
- Large tap targets (minimum 44px)
- Swipe gestures for quick actions
- Portrait-first layout

#### Progressive Web App (PWA)
- Installable on home screen
- Offline caching of critical pages
- Push notifications support
- Background sync
- App-like experience

#### Real-Time Updates
- Socket.IO with auto-reconnect
- Delivery assignment notifications
- Status change broadcasts
- Route optimization updates
- Customer location tracking

#### Offline Support
- Queue delivery status updates
- Cache COD collections
- Auto-sync on reconnection
- Local order snapshots

### Installing Delivery PWA

#### On iOS (iPhone/iPad)

1. Open Safari on your iPhone/iPad
2. Navigate to delivery portal URL (local or production)
3. Tap the Share button (square with arrow)
4. Scroll down and tap "Add to Home Screen"
5. Tap "Add" to confirm
6. The app icon appears on your home screen

#### On Android

1. Open Chrome on your Android device
2. Navigate to delivery portal URL
3. Tap the menu button (three dots)
4. Tap "Add to Home Screen" or "Install App"
5. Tap "Add" or "Install" to confirm
6. The app icon appears on your home screen

### Mobile Delivery Workflow

```text
┌─────────────────────────────────────────────────────────────┐
│ DELIVERY AGENT WORKFLOW                                      │
├─────────────────────────────────────────────────────────────┤
│ 1. Open Delivery PWA from home screen                       │
│ 2. View assigned deliveries (sorted by priority)           │
│ 3. Tap delivery to view details & route                    │
│ 4. Tap "Out for Delivery" to start delivery                │
│ 5. Navigate using integrated map                            │
│ 6. Tap "Delivered" on completion                           │
│ 7. Collect COD (if applicable)                              │
│ 8. Automatic sync to TiDB (online or offline)              │
└─────────────────────────────────────────────────────────────┘
```

### Mobile Delivery UI Components

#### Dashboard
- Assigned deliveries list
- Delivery count badge
- Today's completed count
- Offline status indicator
- Quick actions (refresh, sync)

#### Delivery Detail
- Customer information
- Delivery address with map
- Order items summary
- Delivery instructions
- Status update buttons
- COD collection form
- Customer contact (call/message)

#### History
- Searchable delivery history
- Filter by status
- Date range selection
- Delivery metrics

### Mobile Delivery Best Practices

- **Use PWA** — better performance than browser
- **Enable notifications** — receive delivery assignments instantly
- **Keep app updated** — refresh on reconnection
- **Check sync status** — verify offline queue is empty
- **Report issues** — use in-app feedback for problems

### Mobile Delivery Troubleshooting

| Issue | Solution |
|-------|----------|
| **PWA not installing** | Check browser compatibility, ensure HTTPS |
| **Notifications not working** | Enable browser notifications, check permissions |
| **Offline mode stuck** | Check network, trigger manual sync |
| **Map not loading** | Verify Google Maps API key is configured |
| **Status not updating** | Check TiDB connectivity, verify sync queue |

## 🔌 Realtime Updates (Socket.IO)

### Why Socket.IO?

Real-time updates are critical for bakery operations:
- **Kitchen Display System** — live order updates for kitchen staff
- **Delivery notifications** — instant delivery assignments
- **Admin dashboard** — real-time sales and inventory updates
- **Customer portal** — order status updates
- **Multi-worker sync** — consistent state across Render workers

### Socket.IO Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ CLIENT (Browser/Mobile)                                      │
│  - Customer Portal                                           │
│  - Admin Portal                                             │
│  - Delivery Portal                                          │
└─────────────────────────────────────────────────────────────┘
                          ↓ Socket.IO
┌─────────────────────────────────────────────────────────────┐
│ REDIS MESSAGE QUEUE                                         │
│  - Enables multi-worker broadcasts                          │
│  - Decouples websockets from app instances                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ FLASK APP (Multiple Workers on Render)                      │
│  - Worker 1, Worker 2, Worker 3...                          │
│  - All receive and broadcast events                         │
└─────────────────────────────────────────────────────────────┘
```

### Socket.IO Events

| Event | Purpose | Listeners |
|-------|---------|-----------|
| `order_updated` | Order status changed | Customer, Admin, KDS |
| `kds_refresh` | Kitchen display refresh | KDS only |
| `delivery_updated` | Delivery status changed | Delivery, Admin |
| `analytics_updated` | Sales data updated | Admin dashboard |
| `inventory_alert` | Low stock warning | Admin only |

### Socket.IO Configuration

```python
# config/base.py
SOCKETIO_ASYNC_MODE = "gevent"  # Production
SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
SOCKETIO_MESSAGE_QUEUE = os.environ.get("SOCKETIO_MESSAGE_QUEUE") or REDIS_URL

# app.py
socketio.init_app(
    app,
    async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "threading"),
    cors_allowed_origins=build_socketio_origins(app),
    message_queue=message_queue,
)
```

### Gunicorn Worker Configuration

```python
# gunicorn.conf.py
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"
```

This worker class is required for Socket.IO to work correctly with Gunicorn.

### Client-Side Socket.IO

```javascript
// templates/delivery/base_delivery.html
const socket = io({
  query: { portal: 'delivery' },
  transports: ['websocket', 'polling'],
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 60000,
  randomizationFactor: 0.2,
});

socket.on('delivery_updated', () => {
  const live = document.querySelector('[data-live-refresh]');
  if (live) window.location.reload();
});
```

### Socket.IO Best Practices

- **Use Redis message queue** — required for multi-worker deployments
- **Enable reconnection** — handle network interruptions gracefully
- **Limit event payload** — keep event data small
- **Use rooms** — segment events by portal/role
- **Fallback to polling** — websocket may not work in all networks

### Socket.IO Troubleshooting

| Issue | Solution |
|-------|----------|
| **WebSockets not connecting** | Check Redis URL, verify gevent-websocket worker |
| **Events not received** | Verify room subscription, check message queue |
| **Multi-worker sync issues** | Ensure Redis message queue is configured |
| **Connection drops** | Check reconnection settings, verify network stability |

## 🔌 API Documentation

### API Versioning

| Version | Path | Status | Purpose |
|---------|------|--------|---------|
| v1 | `/api/v1/*` | Stable (deprecating) | Legacy API endpoints |
| v2 | `/api/v2/*` | Active | Modern API with JWT, sync, QR |

### API v1 Endpoints

- `GET /api/v1/products` — List products
- `GET /api/v1/products/<id>` — Get product details
- `POST /api/v1/coupon/validate` — Validate coupon code
- `GET /api/v1/search` — Search products

### API v2 Endpoints

**Authentication:**
- `POST /api/v2/auth/login` — JWT login
- `POST /api/v2/auth/refresh` — Refresh JWT token
- `POST /api/v2/auth/logout` — Logout

**Synchronization:**
- `POST /api/v2/sync/flush` — Flush offline sync queue
- `GET /api/v2/sync/status` — Get sync status
- `POST /api/v2/sync/resolve-conflict` — Resolve sync conflict

**QR Codes:**
- `POST /api/v2/qr/generate` — Generate QR code
- `POST /api/v2/qr/verify` — Verify QR code

**Push Notifications:**
- `POST /api/v2/push/register` — Register push device
- `DELETE /api/v2/push/unregister` — Unregister device

**Search:**
- `GET /api/v2/search` — Advanced search with filters
- `GET /api/v2/search/suggestions` — Search suggestions

## Operations features

| Feature | Admin route |
|---------|-------------|
| POS (offline queue) | `/admin/pos` |
| Kitchen display | `/admin/kds` |
| Forecasts | `/admin/forecasts` |
| Dynamic pricing | `/admin/pricing` |
| Subscriptions | `/admin/subscriptions` |
| Audit & alerts | `/admin/audit` |
| Queue monitor | `/admin/queue-monitor` |
| Offline / conflicts | `/admin/offline` |
| QR scanner | `/admin/qr-scanner` |

## Security

- Production rejects SQLite URIs and weak `SECRET_KEY` values
- Secure session cookies, ProxyFix, CSP, HTTPS redirect
- Payment state machine with transition audit log
- Fraud alerts on coupon abuse and rapid repeat orders
- RBAC via `utils/permissions.py` (`roles_required` on sensitive routes)

## Testing

```bash
pytest tests/ -q
```

## Troubleshooting

| Issue | Check |
|-------|--------|
| Render boot fails | `/healthz`, Redis URL, Cloudinary vars, TiDB IP allowlist |
| Migrations | `flask db upgrade` with `FLASK_APP=app:create_app` |
| Celery tasks missing | `celery -A celery_app.celery_app inspect registered` |
| Offline backlog | Admin → Offline / Sync → Flush queue |
| WebSockets | Redis reachable; single worker on free tier is OK |

## License

Proprietary — SweetCrumbs Bakery platform.
