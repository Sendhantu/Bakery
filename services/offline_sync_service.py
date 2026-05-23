import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from exceptions import ValidationError
from exceptions import ConflictError
from models import (
    Delivery,
    Order,
    OrderItem,
    Payment,
    ProductVariant,
    RawMaterial,
    SyncConflict,
    User,
    db,
)


class OfflineSyncService:
    def __init__(self, app, audit_service):
        self.app = app
        self.audit_service = audit_service
        self.enabled = bool(
            app.config.get("OFFLINE_SYNC_ENABLED", False)
            and app.config.get("PORTAL_ROLE") in {"admin", "delivery"}
        )
        self.db_path = app.config.get("OFFLINE_SYNC_DB_PATH")
        self.lock = threading.Lock()
        if self.enabled and self.db_path:
            self._ensure_tables()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_tables(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_action_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT UNIQUE NOT NULL,
                    action_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expected_version INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    queued_at TEXT NOT NULL,
                    synced_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_snapshots (
                    scope TEXT NOT NULL,
                    entity_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, entity_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_sync_conflicts (
                    request_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    local_payload_json TEXT NOT NULL,
                    remote_payload_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def is_online(self):
        try:
            # Check DB connectivity
            db.session.execute(text("SELECT 1"))
        except Exception:
            db.session.rollback()
            return False

        # Also check Redis if configured for stronger online detection
        try:
            redis_url = self.app.config.get("REDIS_URL") or self.app.config.get("SOCKETIO_MESSAGE_QUEUE")
            if redis_url:
                from redis import Redis

                Redis.from_url(redis_url).ping()
        except Exception:
            return False
        return True

    def cache_snapshot(self, scope, entity_key, payload):
        if not self.enabled:
            return
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO offline_snapshots (scope, entity_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, entity_key)
                DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (
                    scope,
                    str(entity_key),
                    json.dumps(payload, sort_keys=True, default=str),
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.commit()

    def list_snapshots(self, scope):
        if not self.enabled:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM offline_snapshots
                WHERE scope = ?
                ORDER BY updated_at DESC
                """,
                (scope,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_snapshot(self, scope, entity_key):
        if not self.enabled:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM offline_snapshots
                WHERE scope = ? AND entity_key = ?
                """,
                (scope, str(entity_key)),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def queue_action(
        self,
        action_type,
        entity_type,
        entity_id,
        payload,
        *,
        expected_version=None,
        request_id=None,
    ):
        if not self.enabled:
            raise ValidationError("Offline sync is not enabled for this portal.")

        request_id = request_id or str(uuid.uuid4())
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO offline_action_queue
                (request_id, action_type, entity_type, entity_id, payload_json, expected_version, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    action_type,
                    entity_type,
                    str(entity_id),
                    json.dumps(payload, sort_keys=True, default=str),
                    expected_version,
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.commit()
        return request_id

    def pending_actions(self, limit=None):
        if not self.enabled:
            return []
        sql = """
            SELECT * FROM offline_action_queue
            WHERE status IN ('pending', 'retry')
            ORDER BY id ASC
        """
        parameters = ()
        if limit:
            sql += " LIMIT ?"
            parameters = (int(limit),)
        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def mark_synced(self, request_id):
        if not self.enabled:
            return
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE offline_action_queue
                SET status='synced', synced_at=?
                WHERE request_id=?
                """,
                (datetime.utcnow().isoformat(), request_id),
            )
            connection.commit()

    def mark_retry(self, request_id, error_message):
        if not self.enabled:
            return
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE offline_action_queue
                SET status='retry', attempts=attempts+1, last_error=?
                WHERE request_id=?
                """,
                (str(error_message)[:500], request_id),
            )
            connection.commit()

    def record_conflict(self, request_id, entity_type, entity_id, action_type, local_payload, remote_payload):
        if not self.enabled:
            return
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO offline_sync_conflicts
                (request_id, entity_type, entity_id, action_type, local_payload_json, remote_payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    entity_type,
                    str(entity_id),
                    action_type,
                    json.dumps(local_payload, sort_keys=True, default=str),
                    json.dumps(remote_payload, sort_keys=True, default=str),
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE offline_action_queue
                SET status='conflict', attempts=attempts+1, last_error='Version conflict'
                WHERE request_id=?
                """,
                (request_id,),
            )
            connection.commit()

        db.session.add(
            SyncConflict(
                entity_type=entity_type,
                entity_id=str(entity_id),
                action_type=action_type,
                local_payload=json.dumps(local_payload, sort_keys=True, default=str),
                remote_payload=json.dumps(remote_payload, sort_keys=True, default=str),
            )
        )

    def cache_variant(self, variant):
        self.cache_snapshot(
            "variants",
            variant.id,
            {
                "id": variant.id,
                "product_id": variant.product_id,
                "branch_id": variant.branch_id,
                "name": variant.name,
                "stock": variant.stock,
                "price": float(variant.price or 0),
                "sku": variant.sku,
                "barcode": variant.barcode,
                "version": variant.version,
                "product_name": variant.product.name if variant.product else "",
            },
        )

    def cache_material(self, material):
        self.cache_snapshot(
            "raw_materials",
            material.id,
            {
                "id": material.id,
                "branch_id": material.branch_id,
                "name": material.name,
                "stock": float(material.stock or 0),
                "unit": material.unit,
                "reorder_level": float(material.reorder_level or 0),
                "version": material.version,
            },
        )

    def cache_order(self, order):
        self.cache_snapshot(
            "orders",
            order.id,
            {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "payment_status": order.payment_status,
                "customer_name": order.customer.name if order.customer else "",
                "phone": order.phone,
                "city": order.city,
                "total": float(order.total or 0),
                "delivery_date": order.delivery_date.isoformat()
                if order.delivery_date
                else None,
                "delivery_slot": order.delivery_slot,
                "version": order.version,
            },
        )

    def cache_delivery(self, delivery):
        self.cache_snapshot(
            "deliveries",
            delivery.id,
            {
                "id": delivery.id,
                "order_id": delivery.order_id,
                "agent_id": delivery.agent_id,
                "status": delivery.status,
                "eta_minutes": delivery.eta_minutes,
                "version": delivery.version,
                "order_number": delivery.order.order_number if delivery.order else "",
            },
        )

    def queue_variant_stock_update(self, variant, stock, *, actor_id=None):
        return self.queue_variant_stock_update_by_id(
            variant.id,
            stock,
            actor_id=actor_id,
            expected_version=variant.version,
            snapshot_payload={
                "id": variant.id,
                "product_id": variant.product_id,
                "branch_id": variant.branch_id,
                "name": variant.name,
                "stock": int(stock),
                "price": float(variant.price or 0),
                "sku": variant.sku,
                "barcode": variant.barcode,
                "version": variant.version,
                "product_name": variant.product.name if variant.product else "",
            },
        )

    def queue_variant_stock_update_by_id(
        self, variant_id, stock, *, actor_id=None, expected_version=None, snapshot_payload=None
    ):
        request_id = self.queue_action(
            "update_variant_stock",
            "ProductVariant",
            variant_id,
            {"stock": int(stock), "actor_id": actor_id},
            expected_version=expected_version,
        )
        if snapshot_payload is None:
            snapshot_payload = self.get_snapshot("variants", variant_id) or {"id": variant_id}
            snapshot_payload["stock"] = int(stock)
            snapshot_payload["version"] = expected_version or snapshot_payload.get("version")
        self.cache_snapshot("variants", variant_id, snapshot_payload)
        return request_id

    def queue_material_stock_update(self, material, stock, *, actor_id=None):
        return self.queue_material_stock_update_by_id(
            material.id,
            stock,
            actor_id=actor_id,
            expected_version=material.version,
            snapshot_payload={
                "id": material.id,
                "branch_id": material.branch_id,
                "name": material.name,
                "stock": float(stock),
                "unit": material.unit,
                "reorder_level": float(material.reorder_level or 0),
                "version": material.version,
            },
        )

    def queue_material_stock_update_by_id(
        self, material_id, stock, *, actor_id=None, expected_version=None, snapshot_payload=None
    ):
        request_id = self.queue_action(
            "update_raw_material_stock",
            "RawMaterial",
            material_id,
            {"stock": float(stock), "actor_id": actor_id},
            expected_version=expected_version,
        )
        if snapshot_payload is None:
            snapshot_payload = self.get_snapshot("raw_materials", material_id) or {"id": material_id}
            snapshot_payload["stock"] = float(stock)
            snapshot_payload["version"] = expected_version or snapshot_payload.get("version")
        self.cache_snapshot("raw_materials", material_id, snapshot_payload)
        return request_id

    def queue_order_status_update(self, order, new_status, *, actor_id=None):
        return self.queue_order_status_update_by_id(
            order.id,
            new_status,
            actor_id=actor_id,
            expected_version=order.version,
            snapshot_payload={
                "id": order.id,
                "order_number": order.order_number,
                "status": new_status,
                "payment_status": order.payment_status,
                "customer_name": order.customer.name if order.customer else "",
                "phone": order.phone,
                "city": order.city,
                "total": float(order.total or 0),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "delivery_slot": order.delivery_slot,
                "version": order.version,
            },
        )

    def queue_order_status_update_by_id(
        self, order_id, new_status, *, actor_id=None, expected_version=None, snapshot_payload=None
    ):
        request_id = self.queue_action(
            "update_order_status",
            "Order",
            order_id,
            {"status": new_status, "actor_id": actor_id},
            expected_version=expected_version,
        )
        if snapshot_payload is None:
            snapshot_payload = self.get_snapshot("orders", order_id) or {"id": order_id}
            snapshot_payload["status"] = new_status
            snapshot_payload["version"] = expected_version or snapshot_payload.get("version")
        self.cache_snapshot("orders", order_id, snapshot_payload)
        return request_id

    def queue_delivery_status_update(self, delivery, new_status, *, actor_id=None):
        return self.queue_delivery_status_update_by_id(
            delivery.id,
            new_status,
            actor_id=actor_id,
            expected_version=delivery.version,
            snapshot_payload={
                "id": delivery.id,
                "order_id": delivery.order_id,
                "agent_id": delivery.agent_id,
                "status": new_status,
                "eta_minutes": delivery.eta_minutes,
                "version": delivery.version,
                "order_number": delivery.order.order_number if delivery.order else "",
            },
        )

    def queue_delivery_status_update_by_id(
        self, delivery_id, new_status, *, actor_id=None, expected_version=None, snapshot_payload=None
    ):
        request_id = self.queue_action(
            "update_delivery_status",
            "Delivery",
            delivery_id,
            {"status": new_status, "actor_id": actor_id},
            expected_version=expected_version,
        )
        if snapshot_payload is None:
            snapshot_payload = self.get_snapshot("deliveries", delivery_id) or {"id": delivery_id}
            snapshot_payload["status"] = new_status
            snapshot_payload["version"] = expected_version or snapshot_payload.get("version")
        self.cache_snapshot("deliveries", delivery_id, snapshot_payload)
        return request_id

    def queue_cod_collection(self, order, amount, payment_mode, *, actor_id=None):
        return self.queue_cod_collection_by_id(
            order.id,
            amount,
            payment_mode,
            actor_id=actor_id,
            expected_version=order.version,
            snapshot_payload={
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "payment_status": "PAID",
                "customer_name": order.customer.name if order.customer else "",
                "phone": order.phone,
                "city": order.city,
                "total": float(order.total or 0),
                "delivery_date": order.delivery_date.isoformat() if order.delivery_date else None,
                "delivery_slot": order.delivery_slot,
                "version": order.version,
            },
        )

    def queue_cod_collection_by_id(
        self,
        order_id,
        amount,
        payment_mode,
        *,
        actor_id=None,
        expected_version=None,
        snapshot_payload=None,
    ):
        request_id = self.queue_action(
            "collect_cod_payment",
            "Order",
            order_id,
            {
                "amount": float(amount),
                "payment_mode": payment_mode,
                "actor_id": actor_id,
            },
            expected_version=expected_version,
        )
        if snapshot_payload is None:
            snapshot_payload = self.get_snapshot("orders", order_id) or {"id": order_id}
            snapshot_payload["payment_status"] = "PAID"
            snapshot_payload["version"] = expected_version or snapshot_payload.get("version")
        self.cache_snapshot("orders", order_id, snapshot_payload)
        return request_id

    def flush_pending_actions(self, limit=None):
        if not self.enabled or not self.is_online():
            return {"synced": 0, "conflicts": 0, "retried": 0}

        synced = 0
        conflicts = 0
        retried = 0
        for action in self.pending_actions(limit=limit or self.app.config.get("SYNC_BATCH_SIZE", 50)):
            request_id = action["request_id"]
            payload = json.loads(action["payload_json"])
            self.app.logger.debug("offline_sync_attempt", extra={"request_id": request_id, "action": action["action_type"], "entity": action.get("entity_type"), "entity_id": action.get("entity_id"), "attempts": action.get("attempts", 0)})
            try:
                self._apply_action(
                    request_id=request_id,
                    action_type=action["action_type"],
                    entity_id=action["entity_id"],
                    payload=payload,
                    expected_version=action["expected_version"],
                )
                self.mark_synced(request_id)
                db.session.commit()
                synced += 1
            except ValidationError as exc:
                self.app.logger.warning("offline_sync_retry", exc_info=exc, extra={"request_id": request_id})
                self.mark_retry(request_id, exc)
                db.session.rollback()
                retried += 1
            except ConflictError as exc:
                self.app.logger.warning("offline_sync_conflict", exc_info=exc, extra={"request_id": request_id})
                self.record_conflict(
                    request_id,
                    exc.entity_type,
                    exc.entity_id,
                    action["action_type"],
                    payload,
                    exc.remote_payload,
                )
                db.session.commit()
                conflicts += 1
            except SQLAlchemyError as exc:
                self.app.logger.error("offline_sync_error", exc_info=exc, extra={"request_id": request_id})
                self.mark_retry(request_id, exc)
                db.session.rollback()
                retried += 1
            except Exception as exc:  # pragma: no cover
                self.app.logger.exception("offline_sync_unexpected", exc_info=exc, extra={"request_id": request_id})
                self.mark_retry(request_id, exc)
                db.session.rollback()
                retried += 1
        if conflicts or retried:
            self.audit_service.alert(
                "offline_sync_backlog",
                "Offline sync attention required",
                f"synced={synced}, conflicts={conflicts}, retried={retried}",
                severity="warning" if conflicts == 0 else "high",
            )
            db.session.commit()
        return {"synced": synced, "conflicts": conflicts, "retried": retried}

    def _apply_action(self, *, request_id, action_type, entity_id, payload, expected_version):
        if self.audit_service.already_processed(request_id):
            return

        if action_type == "update_variant_stock":
            self._apply_variant_stock_update(request_id, entity_id, payload, expected_version)
            return
        if action_type == "update_raw_material_stock":
            self._apply_raw_material_stock_update(request_id, entity_id, payload, expected_version)
            return
        if action_type == "update_order_status":
            self._apply_order_status_update(request_id, entity_id, payload, expected_version)
            return
        if action_type == "update_delivery_status":
            self._apply_delivery_status_update(request_id, entity_id, payload, expected_version)
            return
        if action_type == "collect_cod_payment":
            self._apply_cod_collection(request_id, entity_id, payload, expected_version)
            return
        if action_type == "create_pos_sale":
            self._apply_pos_sale(request_id, payload)
            return
        raise ValidationError(f"Unsupported offline action: {action_type}")

    def _assert_version(self, entity, expected_version, entity_type):
        if expected_version is None:
            return
        current_version = int(getattr(entity, "version", 0) or 0)
        if current_version > int(expected_version):
            raise ConflictError(
                entity_type=entity_type,
                entity_id=entity.id,
                remote_payload={
                    "id": entity.id,
                    "version": current_version,
                },
            )

    def _apply_variant_stock_update(self, request_id, entity_id, payload, expected_version):
        variant = db.session.get(ProductVariant, int(entity_id))
        if variant is None:
            raise ValidationError("Product variant not found during sync.")
        self._assert_version(variant, expected_version, "ProductVariant")
        variant.stock = int(payload["stock"])
        variant.version = int(variant.version or 0) + 1
        self.audit_service.record(
            "offline_variant_stock_sync",
            "ProductVariant",
            variant.id,
            actor_id=payload.get("actor_id"),
            branch_id=variant.branch_id,
            request_id=request_id,
            metadata={"stock": variant.stock},
            change_summary=f"Stock synced to {variant.stock}",
        )
        self.cache_variant(variant)

    def _apply_raw_material_stock_update(self, request_id, entity_id, payload, expected_version):
        material = db.session.get(RawMaterial, int(entity_id))
        if material is None:
            raise ValidationError("Raw material not found during sync.")
        self._assert_version(material, expected_version, "RawMaterial")
        material.stock = payload["stock"]
        material.version = int(material.version or 0) + 1
        self.audit_service.record(
            "offline_raw_material_sync",
            "RawMaterial",
            material.id,
            actor_id=payload.get("actor_id"),
            branch_id=material.branch_id,
            request_id=request_id,
            metadata={"stock": float(material.stock or 0)},
            change_summary=f"Material stock synced to {material.stock}",
        )
        self.cache_material(material)

    def _apply_order_status_update(self, request_id, entity_id, payload, expected_version):
        order = db.session.get(Order, int(entity_id))
        if order is None:
            raise ValidationError("Order not found during sync.")
        self._assert_version(order, expected_version, "Order")
        order.status = str(payload["status"]).strip().upper()
        order.mark_status_change()
        self.audit_service.record(
            "offline_order_status_sync",
            "Order",
            order.id,
            actor_id=payload.get("actor_id"),
            branch_id=order.branch_id,
            request_id=request_id,
            metadata={"status": order.status},
            change_summary=f"Order status synced to {order.status}",
        )
        self.cache_order(order)

    def _apply_delivery_status_update(self, request_id, entity_id, payload, expected_version):
        delivery = db.session.get(Delivery, int(entity_id))
        if delivery is None:
            raise ValidationError("Delivery not found during sync.")
        self._assert_version(delivery, expected_version, "Delivery")
        delivery.status = str(payload["status"]).strip().upper()
        delivery.version = int(delivery.version or 0) + 1
        delivery.last_status_at = datetime.utcnow()
        self.audit_service.record(
            "offline_delivery_status_sync",
            "Delivery",
            delivery.id,
            actor_id=payload.get("actor_id"),
            branch_id=delivery.branch_id,
            request_id=request_id,
            metadata={"status": delivery.status},
            change_summary=f"Delivery status synced to {delivery.status}",
        )
        self.cache_delivery(delivery)

    def _apply_cod_collection(self, request_id, entity_id, payload, expected_version):
        order = db.session.get(Order, int(entity_id))
        if order is None:
            raise ValidationError("Order not found during sync.")
        self._assert_version(order, expected_version, "Order")
        payment = order.payment
        if payment is None:
            payment = Payment(order_id=order.id, amount=payload["amount"])
            db.session.add(payment)
            db.session.flush()

        # optimistic check on payment if present
        try:
            from utils.optimistic import assert_version

            assert_version(payment, payload.get("expected_payment_version"), entity_name='Payment')
        except Exception:
            # convert into ConflictError expected by calling code
            raise ConflictError(
                entity_type='Payment',
                entity_id=getattr(payment, 'id', None),
                remote_payload={
                    "id": getattr(payment, 'id', None),
                    "version": int(getattr(payment, 'version', 0) or 0),
                },
            )

        payment.amount = payload["amount"]
        payment.method = f"COD_{str(payload.get('payment_mode', 'CASH')).upper()}"
        payment.transaction_id = payment.transaction_id or f"COD-SYNC-{uuid.uuid4().hex[:10].upper()}"
        payment.transition_to("PAID", actor_id=payload.get("actor_id"), reason="offline_cod_sync")
        order.mark_status_change()
        self.audit_service.record(
            "offline_cod_collection_sync",
            "Order",
            order.id,
            actor_id=payload.get("actor_id"),
            branch_id=order.branch_id,
            request_id=request_id,
            metadata={"payment_status": order.payment_status, "amount": payload["amount"]},
            change_summary="COD payment synced after offline collection",
        )
        self.cache_order(order)

    def queue_pos_sale(
        self,
        *,
        variant_id,
        quantity,
        payment_mode,
        customer_phone="",
        actor_id=None,
    ):
        request_id = self.queue_action(
            "create_pos_sale",
            "Order",
            f"pos-{uuid.uuid4().hex[:8]}",
            {
                "variant_id": int(variant_id),
                "quantity": int(quantity),
                "payment_mode": str(payment_mode or "CASH").upper(),
                "customer_phone": customer_phone,
                "actor_id": actor_id,
            },
        )
        snapshot = self.get_snapshot("variants", variant_id) or {"id": variant_id, "stock": 0}
        snapshot["stock"] = max(0, int(snapshot.get("stock", 0)) - int(quantity))
        self.cache_snapshot("variants", variant_id, snapshot)
        return request_id

    def _apply_pos_sale(self, request_id, payload):
        walkin_email = "walkin@sweetcrumbs.local"
        variant = db.session.get(ProductVariant, int(payload["variant_id"]))
        if variant is None or variant.product is None:
            raise ValidationError("POS variant not found during sync.")
        quantity = max(1, int(payload["quantity"]))
        if int(variant.stock or 0) < quantity:
            raise ValidationError("Insufficient stock to sync POS sale.")

        customer = User.query.filter_by(email=walkin_email).first()
        if customer is None:
            customer = User(
                name="Walk-in Customer",
                email=walkin_email,
                role="customer",
                is_active=True,
                phone=payload.get("customer_phone") or None,
            )
            db.session.add(customer)
            db.session.flush()

        subtotal = variant.price * quantity
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            source="POS",
            status="DELIVERED",
            fulfillment_type="PICKUP",
            payment_method=str(payload.get("payment_mode") or "CASH").upper(),
            payment_status="PAID",
            subtotal=subtotal,
            total=subtotal,
            address_line1=self.app.config["STORE_DETAILS"].get("address_line1", ""),
            city=self.app.config["STORE_DETAILS"].get("city", ""),
            pincode=self.app.config["STORE_DETAILS"].get("pincode", ""),
            phone=payload.get("customer_phone") or self.app.config["STORE_DETAILS"].get("phone_tel", ""),
            delivery_slot="Walk-in",
            delivery_date=datetime.utcnow().date(),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=variant.product_id,
                variant_id=variant.id,
                product_name=variant.product.name,
                variant_name=variant.name,
                quantity=quantity,
                unit_price=variant.price,
                subtotal=subtotal,
            )
        )
        variant.stock = max(0, int(variant.stock or 0) - quantity)
        variant.version = int(variant.version or 0) + 1
        payment = Payment(order_id=order.id, amount=subtotal, method=order.payment_method)
        db.session.add(payment)
        db.session.flush()
        payment.transition_to("PAID", actor_id=payload.get("actor_id"), reason="offline_pos_sync")
        self.audit_service.record(
            "offline_pos_sale_sync",
            "Order",
            order.id,
            actor_id=payload.get("actor_id"),
            branch_id=order.branch_id,
            request_id=request_id,
            metadata={"variant_id": variant.id, "quantity": quantity},
            change_summary=f"POS sale synced for {variant.product.name}",
        )
        self.cache_variant(variant)
        self.cache_order(order)

    def resolve_conflict(self, conflict_id, resolution, *, actor_id=None):
        conflict = db.session.get(SyncConflict, conflict_id)
        if conflict is None or conflict.resolved_at:
            raise ValidationError("Conflict not found or already resolved.")

        local_payload = json.loads(conflict.local_payload or "{}")
        entity_id = conflict.entity_id
        if resolution == "accept_local" and conflict.action_type == "update_variant_stock":
            variant = db.session.get(ProductVariant, int(entity_id))
            if variant:
                variant.stock = int(local_payload.get("stock", variant.stock))
                variant.version = int(variant.version or 0) + 1
                self.cache_variant(variant)
        elif resolution == "accept_remote":
            pass
        conflict.resolved_at = datetime.utcnow()
        self.audit_service.record(
            "sync_conflict_resolved",
            conflict.entity_type,
            conflict.entity_id,
            actor_id=actor_id,
            metadata={"resolution": resolution, "action_type": conflict.action_type},
            change_summary=f"Resolved sync conflict via {resolution}",
        )
        db.session.commit()
        return conflict


class ConflictError(Exception):
    def __init__(self, *, entity_type, entity_id, remote_payload):
        super().__init__("Version conflict")
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.remote_payload = remote_payload
