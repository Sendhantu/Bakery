# SweetCrumbs Test Suite

## Local Setup

Install the application dependencies and pytest:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pytest
```

Run the full suite:

```bash
python -m pytest
```

The pytest fixtures create a disposable SQLite database per test app and stub
email, SMS, WhatsApp, push, weather, route planning, reverse geocoding, and LLM
integrations so tests stay hermetic. No real customer messages or external API
calls should happen during tests.

## Migration Checks

Run the lightweight migration graph check:

```bash
python scripts/check_migration_heads.py
```

Run migrations against a MySQL-compatible database, matching the CI check:

```bash
export FLASK_APP=wsgi:app
export FLASK_ENV=testing
export DATABASE_URL=mysql+pymysql://root:root@127.0.0.1:3306/sweetcrumbs_test
python -m flask db upgrade
python -m flask db current
```

CI uses MySQL 8 as the closest always-available MySQL-wire-protocol stand-in for
TiDB. SQLite remains the fast unit/integration test database.

## Covered Areas

- Route smoke tests for customer, admin, and delivery portals.
- Admin tier permissions for finance, audit, staff, inventory, analytics, and
  triage routes.
- Stock deduction service behavior, including insufficient-stock rollback
  expectations and stock movement recording.
- Finance reconciliation, profit and loss math, exports, backfill idempotency,
  and encrypted financial fields at rest.
- Order reversal workflows for cancellation and refund impacts.
- Counter POS sale creation through the shared order pipeline, including channel
  recording, shared stock contention, finance rows, realtime emits, and receipt
  PDF generation.
- Recurring subscription order generation through the shared order pipeline,
  including payment-pending fallback, insufficient-stock logs, and next-date
  advancement.
- Realtime event room targeting for admin, KDS, customer, and specific delivery
  agent rooms without `broadcast=True`.
- Demand insight calculations and weather-service persistence with mocked
  weather responses.

## Known Gaps

- The suite mocks Socket.IO emits; it does not spin up Redis-backed multi-process
  Socket.IO workers. Use staging for that cross-process room behavior.
- Checkout remains a large route-level flow with forms, session cart state, and
  payment side effects. The suite covers the stock and finance service contracts
  beneath it, but full browser checkout E2E would be a useful next layer.
- Product variant stock changes still happen in route/POS flows while raw
  material deduction is service-layered. Extracting variant stock adjustment into
  a small service would make it easier to test every checkout/POS path uniformly.
- CI validates MySQL-compatible migrations; true TiDB distributed commit and DDL
  behavior should still be verified in a TiDB-backed staging environment before
  production releases.
