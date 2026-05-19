from datetime import datetime

from .base import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(80), unique=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    change_summary = db.Column(db.Text)
    metadata_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship("User")
    branch = db.relationship("Branch")

    __table_args__ = (
        db.Index("idx_audit_entity_created", "entity_type", "entity_id", "created_at"),
        db.Index("idx_audit_actor_created", "actor_id", "created_at"),
    )


class OperationalAlert(db.Model):
    __tablename__ = "operational_alerts"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    alert_type = db.Column(db.String(80), nullable=False)
    severity = db.Column(db.String(20), default="warning")
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch")
    user = db.relationship("User")


class InventoryForecast(db.Model):
    __tablename__ = "inventory_forecasts"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    forecast_date = db.Column(db.Date, nullable=False)
    horizon = db.Column(db.String(20), default="daily")
    predicted_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    ingredient_projection_json = db.Column(db.Text)
    confidence_score = db.Column(db.Numeric(5, 2), default=0)
    alert_level = db.Column(db.String(20), default="normal")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch")
    product = db.relationship("Product", backref="forecasts")

    __table_args__ = (
        db.UniqueConstraint(
            "branch_id",
            "product_id",
            "forecast_date",
            "horizon",
            name="uq_inventory_forecast_scope",
        ),
    )


class DeliveryRoutePlan(db.Model):
    __tablename__ = "delivery_route_plans"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    agent_id = db.Column(db.Integer, db.ForeignKey("delivery_agents.id"))
    route_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(30), default="planned")
    stop_count = db.Column(db.Integer, default=0)
    total_distance_km = db.Column(db.Numeric(10, 2), default=0)
    estimated_duration_minutes = db.Column(db.Integer, default=0)
    route_payload_json = db.Column(db.Text)
    route_cache_key = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship("Branch")
    agent = db.relationship("DeliveryAgent", backref="route_plans")


class StaffShift(db.Model):
    __tablename__ = "staff_shifts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    role = db.Column(db.String(40), nullable=False)
    shift_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default="scheduled")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch", backref="staff_shifts")


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    shift_id = db.Column(db.Integer, db.ForeignKey("staff_shifts.id"))
    clock_in_at = db.Column(db.DateTime)
    clock_out_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="present")
    worked_minutes = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch", backref="attendance_records")
    shift = db.relationship("StaffShift", backref="attendance_records")


class SalaryRecord(db.Model):
    __tablename__ = "salary_records"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(20), default="due")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch", backref="salary_records")
    user = db.relationship("User", backref="salary_records")


class SearchAnalytics(db.Model):
    __tablename__ = "search_analytics"
    id = db.Column(db.Integer, primary_key=True)
    query_text = db.Column(db.String(255), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    hit_count = db.Column(db.Integer, default=0)
    last_searched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint("query_text", "product_id", name="uq_search_query_product"),
    )


class BackupVerification(db.Model):
    __tablename__ = "backup_verifications"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), default="unknown")
    details = db.Column(db.Text)
    verified_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class QueueMetric(db.Model):
    __tablename__ = "queue_metrics"
    id = db.Column(db.Integer, primary_key=True)
    queue_name = db.Column(db.String(80), nullable=False)
    backlog = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ApiUsageLog(db.Model):
    __tablename__ = "api_usage_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    version = db.Column(db.String(20), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    status_code = db.Column(db.Integer, default=200)
    latency_ms = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


class FraudAlert(db.Model):
    __tablename__ = "fraud_alerts"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    alert_type = db.Column(db.String(80), nullable=False)
    severity = db.Column(db.String(20), default="medium")
    details = db.Column(db.Text)
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order = db.relationship("Order", backref="fraud_alerts")
    user = db.relationship("User", backref="fraud_alerts")


class PushDevice(db.Model):
    __tablename__ = "push_devices"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    portal_role = db.Column(db.String(40), nullable=False)
    platform = db.Column(db.String(40), default="web")
    device_token = db.Column(db.String(255), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="push_devices")


class PricingRule(db.Model):
    __tablename__ = "pricing_rules"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    name = db.Column(db.String(120), nullable=False)
    rule_type = db.Column(db.String(40), nullable=False)
    starts_at = db.Column(db.DateTime)
    ends_at = db.Column(db.DateTime)
    percent_discount = db.Column(db.Numeric(5, 2), default=0)
    max_batch_age_hours = db.Column(db.Integer)
    applies_after_hour = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    branch = db.relationship("Branch")
    category = db.relationship("Category")


class SubscriptionSchedule(db.Model):
    __tablename__ = "subscription_schedules"
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("subscriptions.id"), nullable=False, unique=True
    )
    next_run_at = db.Column(db.DateTime, nullable=False)
    skipped_until = db.Column(db.DateTime)
    last_generated_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    subscription = db.relationship("Subscription", backref="schedule")


class CashbackWalletEntry(db.Model):
    __tablename__ = "cashback_wallet_entries"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    entry_type = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="wallet_entries")
    order = db.relationship("Order", backref="wallet_entries")


class ReferralReward(db.Model):
    __tablename__ = "referral_rewards"
    id = db.Column(db.Integer, primary_key=True)
    referrer_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    referred_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    reward_points = db.Column(db.Integer, default=0)
    reward_amount = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    referrer = db.relationship("User", foreign_keys=[referrer_user_id])
    referred = db.relationship("User", foreign_keys=[referred_user_id])
    order = db.relationship("Order")


class SyncConflict(db.Model):
    __tablename__ = "sync_conflicts"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.String(80), nullable=False)
    action_type = db.Column(db.String(80), nullable=False)
    local_payload = db.Column(db.Text)
    remote_payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)
