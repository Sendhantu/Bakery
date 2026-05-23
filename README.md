# SweetCrumbs Bakery — Hybrid Production Platform

Flask modular monolith for bakery e-commerce, local admin operations, mobile delivery, offline-first sync, and Render + TiDB Cloud deployment.

## Architecture (hybrid)

```text
PUBLIC (Render)
  └── Customer portal (PORTAL_ROLE=customer) — ONLY public-facing app

LOCAL / PRIVATE (your laptop & delivery phones)
  ├── Admin portal (PORTAL_ROLE=admin) — :5001
  └── Delivery portal (PORTAL_ROLE=delivery) — :5002 PWA

SHARED CLOUD
  ├── TiDB Cloud (primary MySQL-compatible database)
  ├── Redis (Socket.IO, Celery, cache, rate limits)
  └── Cloudinary (product images, invoice PDFs)
```

- **One Flask codebase**, **one TiDB database**, **one Redis cluster**
- **SQLite is never production data** — only local offline queue files under `instance/offline/`
- Production schema: `flask db upgrade` (see `migrations/versions/`)

## Quick start (local development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configure DB_*, REDIS_URL, Cloudinary

# Terminal 1 — customer
cd customer_app && cp .env.example .env && python app.py

# Terminal 2 — admin (offline sync enabled)
cd admin_app && cp .env.example .env && python app.py

# Terminal 3 — delivery (mobile PWA)
cd delivery_app && cp .env.example .env && python app.py
```

| Portal   | URL                      | Role      |
|----------|--------------------------|-----------|
| Customer | http://127.0.0.1:5000    | customer  |
| Admin    | http://127.0.0.1:5001    | admin     |
| Delivery | http://127.0.0.1:5002    | delivery  |

Demo credentials (development only): see startup logs or `output/dev_credentials.json`.

## Render deployment (customer + workers only)

[`render.yaml`](render.yaml) provisions:

1. **sweetcrumbs-redis** — Redis
2. **sweetcrumbs-customer** — Gunicorn + Gevent WebSocket worker
3. **sweetcrumbs-celery-worker** — background tasks
4. **sweetcrumbs-celery-beat** — scheduled jobs

**Not deployed on Render:** admin and delivery portals (run locally).

### Render environment (set in dashboard)

| Variable | Required |
|----------|----------|
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Yes (TiDB) |
| `DB_SSL_CA`, `DB_SSL_VERIFY_CERT`, `DB_SSL_VERIFY_IDENTITY` | Yes |
| `REDIS_URL` | Auto from blueprint |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Auto-generated |
| `CLOUDINARY_*` | Yes |
| `CUSTOMER_PORTAL_URL` | Your Render URL |
| `BOOTSTRAP_SEED_DATA` | `false` in production |

Start command: `gunicorn --config gunicorn.conf.py wsgi:app`

Health check: `GET /healthz` (DB, Redis, Celery broker, Cloudinary)

Pre-deploy: `python scripts/bootstrap_database.py` runs `flask db upgrade`.

## TiDB Cloud setup

1. Create Serverless cluster and database `bakerydb`.
2. Allow your IP (local) and Render outbound IPs.
3. Either:
   - **Recommended:** deploy with `flask db upgrade` via bootstrap script, or
   - Import [`tidb_bootstrap.sql`](tidb_bootstrap.sql) for greenfield SQL seed (regenerate with `python scripts/generate_tidb_bootstrap.py`).

Connection uses `mysql+pymysql://` with TLS from `DB_SSL_*` variables.

## Redis

Required in production for:

- Socket.IO message queue (`SOCKETIO_MESSAGE_QUEUE`)
- Celery broker/result backend
- Flask-Caching and rate limiting

Local: `REDIS_URL=redis://127.0.0.1:6379/0`

## Cloudinary

All product uploads go to Cloudinary (no local `file.save`). Set:

- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

## Celery

```bash
# Worker
celery -A celery_app.celery_app worker --loglevel=info

# Beat (schedules in config/base.py)
celery -A celery_app.celery_app beat --loglevel=info
```

Scheduled jobs include: inventory forecasts, subscription orders, offline sync retry, analytics snapshot, backup verification, birthday loyalty, abandoned-cart WhatsApp reminders.

## Offline-first (admin & delivery)

When TiDB is unreachable:

1. Actions queue to `instance/offline/{portal}_offline_sync.sqlite`
2. Local snapshots keep UI responsive
3. On reconnect, Celery + `/api/v2/sync/flush` push changes to TiDB
4. Version conflicts surface at **Admin → Offline / Sync**

### Offline sync details

- Local buffering: admin and delivery portals use a local SQLite file under `instance/offline/{portal}_offline_sync.sqlite` for queued actions and snapshots. SQLite is strictly local and never used as a production database.
- Automatic resume: when the client regains connectivity the browser triggers a server-side sync endpoint which starts a background flush; Celery beat also runs `retry_offline_sync_actions` every minute.
- Idempotency & duplication avoidance: actions are queued with `request_id` and recorded in an `audit_logs` table to avoid re-applying the same change.
- Conflict handling: if the remote record version is newer, a `sync_conflicts` entry is created. Admins can review and resolve via **Admin → Offline / Sync**.
- Production safety: the app enforces `forbid_sqlite_in_production()` and will abort startup if a SQLite DB URI is detected in `ENV=production`.
Proactive queueing: routes check `offline_sync.is_online()` before writes.

## Mobile delivery

- Responsive delivery templates + PWA manifest/service worker
- Socket.IO reconnect (`delivery_updated` events)
- Offline status/COD queueing with automatic sync

Install: open delivery portal in mobile browser → Add to Home Screen.

## Realtime (Socket.IO)

- Redis message queue enables multi-worker broadcasts
- Events: `order_updated`, `kds_refresh`, `delivery_updated`, `analytics_updated`
- KDS uses sockets with 30s HTTP fallback poll

Gunicorn worker: `geventwebsocket.gunicorn.workers.GeventWebSocketWorker`

## API versions

| Path | Status |
|------|--------|
| `/api/v1/*` | Stable, deprecation headers toward v2 |
| `/api/v2/*` | JWT, sync, QR, push devices, search |

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
