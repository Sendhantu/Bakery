from datetime import datetime

from clock import utcnow
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
    before_value = db.Column(db.Text)
    after_value = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    metadata_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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


class LocalEvent(db.Model):
    __tablename__ = "local_events"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    expected_impact = db.Column(db.String(20), nullable=False, default="medium")
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    creator = db.relationship("User")

    __table_args__ = (
        db.Index("idx_local_events_date", "event_date"),
        db.Index("idx_local_events_impact_date", "expected_impact", "event_date"),
    )


class WeatherSnapshot(db.Model):
    __tablename__ = "weather_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    forecast_date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(40), nullable=False, default="openweathermap")
    location_label = db.Column(db.String(160))
    condition = db.Column(db.String(80))
    description = db.Column(db.String(160))
    temp_min_c = db.Column(db.Numeric(5, 2))
    temp_max_c = db.Column(db.Numeric(5, 2))
    humidity_avg = db.Column(db.Numeric(5, 2))
    precipitation_probability = db.Column(db.Numeric(5, 2))
    fetched_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "forecast_date",
            "source",
            "location_label",
            name="uq_weather_snapshot_scope",
        ),
        db.Index("idx_weather_snapshot_date", "forecast_date"),
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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    branch = db.relationship("Branch", backref="salary_records")
    user = db.relationship("User", backref="salary_records")


class SearchAnalytics(db.Model):
    __tablename__ = "search_analytics"
    id = db.Column(db.Integer, primary_key=True)
    query_text = db.Column(db.String(255), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    hit_count = db.Column(db.Integer, default=0)
    last_searched_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint("query_text", "product_id", name="uq_search_query_product"),
    )


class CustomerActivity(db.Model):
    __tablename__ = "customer_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    event_type = db.Column(db.String(40), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    query_text = db.Column(db.String(255))
    metadata_json = db.Column(db.Text)
    session_id = db.Column(db.String(120))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", backref="customer_activity")
    product = db.relationship("Product")

    __table_args__ = (
        db.Index("idx_customer_activity_user_created", "user_id", "created_at"),
        db.Index("idx_customer_activity_product_created", "product_id", "created_at"),
        db.Index("idx_customer_activity_event_created", "event_type", "created_at"),
    )


class CustomerConsent(db.Model):
    __tablename__ = "customer_consents"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    session_id = db.Column(db.String(120))
    category = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="declined")
    source = db.Column(db.String(40), default="web")
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User")

    __table_args__ = (
        db.Index("idx_customer_consent_user_category", "user_id", "category", "created_at"),
        db.Index("idx_customer_consent_session_category", "session_id", "category", "created_at"),
    )


class ConversionEvent(db.Model):
    __tablename__ = "conversion_events"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(80), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    session_id = db.Column(db.String(120))
    event_name = db.Column(db.String(80), nullable=False)
    path = db.Column(db.String(255))
    source = db.Column(db.String(80))
    medium = db.Column(db.String(80))
    campaign = db.Column(db.String(120))
    content = db.Column(db.String(120))
    term = db.Column(db.String(120))
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    table_id = db.Column(db.Integer, db.ForeignKey("dining_tables.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    amount = db.Column(db.Numeric(10, 2), default=0)
    currency = db.Column(db.String(3), default="INR", nullable=False)
    metadata_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User")
    product = db.relationship("Product")
    order = db.relationship("Order")
    branch = db.relationship("Branch")

    __table_args__ = (
        db.Index("idx_conversion_event_name_created", "event_name", "created_at"),
        db.Index("idx_conversion_branch_created", "branch_id", "created_at"),
        db.Index("idx_conversion_product_created", "product_id", "created_at"),
    )


class WebhookEventLog(db.Model):
    __tablename__ = "webhook_event_logs"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(60), nullable=False)
    event_id = db.Column(db.String(120), nullable=False)
    event_type = db.Column(db.String(120))
    payload_hash = db.Column(db.String(64), nullable=False)
    signature_status = db.Column(db.String(30), default="pending", nullable=False)
    processing_status = db.Column(db.String(30), default="received", nullable=False)
    replayed = db.Column(db.Boolean, default=False, nullable=False)
    error_details = db.Column(db.Text)
    received_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    processed_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
        db.Index("idx_webhook_provider_received", "provider", "received_at"),
        db.Index("idx_webhook_signature_status", "signature_status", "received_at"),
    )


class SecurityEvent(db.Model):
    __tablename__ = "security_events"
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(80), nullable=False)
    severity = db.Column(db.String(20), default="warning", nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    path = db.Column(db.String(255))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(200))
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
    branch = db.relationship("Branch")

    __table_args__ = (
        db.Index("idx_security_event_type_created", "event_type", "created_at"),
        db.Index("idx_security_event_severity_created", "severity", "created_at"),
    )


class OccasionReminder(db.Model):
    __tablename__ = "occasion_reminders"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    occasion_type = db.Column(db.String(60), nullable=False)
    occasion_date = db.Column(db.Date, nullable=False)
    recipient_name = db.Column(db.String(120))
    relationship = db.Column(db.String(80))
    preferred_channel = db.Column(db.String(30), default="email", nullable=False)
    reminder_days_before = db.Column(db.Integer, default=10, nullable=False)
    timezone = db.Column(db.String(80), default="Asia/Kolkata", nullable=False)
    marketing_consent = db.Column(db.Boolean, default=False, nullable=False)
    recommendations_enabled = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", backref=db.backref("occasion_reminders", lazy="dynamic"))
    order = db.relationship("Order", backref=db.backref("occasion_reminders", lazy="dynamic"))

    __table_args__ = (
        db.Index("idx_occasion_user_active", "user_id", "is_active"),
        db.Index("idx_occasion_date", "occasion_date"),
    )


class OccasionReminderLog(db.Model):
    __tablename__ = "occasion_reminder_logs"
    id = db.Column(db.Integer, primary_key=True)
    reminder_id = db.Column(db.Integer, db.ForeignKey("occasion_reminders.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    occasion_year = db.Column(db.Integer, nullable=False)
    campaign = db.Column(db.String(80), default="annual_occasion", nullable=False)
    channel = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), default="sent", nullable=False)
    coupon_id = db.Column(db.Integer, db.ForeignKey("coupons.id"))
    message = db.Column(db.Text)
    error_details = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    reminder = db.relationship("OccasionReminder", backref=db.backref("logs", lazy="dynamic"))
    user = db.relationship("User")
    coupon = db.relationship("Coupon")

    __table_args__ = (
        db.UniqueConstraint(
            "reminder_id",
            "occasion_year",
            "campaign",
            "channel",
            name="uq_occasion_reminder_once_per_year",
        ),
    )


class CorporateCustomer(db.Model):
    __tablename__ = "corporate_customers"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(180), nullable=False)
    gstin = db.Column(db.String(15))
    billing_address = db.Column(db.Text)
    delivery_locations_json = db.Column(db.Text)
    contact_persons_json = db.Column(db.Text)
    approved_payment_terms = db.Column(db.String(120))
    credit_limit = db.Column(db.Numeric(12, 2), default=0)
    outstanding_amount = db.Column(db.Numeric(12, 2), default=0)
    preferred_products_json = db.Column(db.Text)
    contract_pricing_json = db.Column(db.Text)
    account_manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    internal_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    account_manager = db.relationship("User")


class CorporateInquiry(db.Model):
    __tablename__ = "corporate_inquiries"
    id = db.Column(db.Integer, primary_key=True)
    corporate_customer_id = db.Column(db.Integer, db.ForeignKey("corporate_customers.id"))
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    related_order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    status = db.Column(db.String(40), default="new", nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    company_name = db.Column(db.String(180), nullable=False)
    work_email = db.Column(db.String(120), nullable=False)
    mobile = db.Column(db.String(30), nullable=False)
    gstin = db.Column(db.String(15))
    billing_address = db.Column(db.Text)
    delivery_location = db.Column(db.Text, nullable=False)
    required_date = db.Column(db.Date, nullable=False)
    preferred_delivery_time = db.Column(db.String(50))
    people_count = db.Column(db.Integer)
    estimated_quantity = db.Column(db.Integer)
    budget_range = db.Column(db.String(80))
    products_required = db.Column(db.Text)
    custom_branding = db.Column(db.Boolean, default=False, nullable=False)
    dietary_requirements = db.Column(db.Text)
    notes = db.Column(db.Text)
    attachment_filename = db.Column(db.String(255))
    attachment_path = db.Column(db.String(500))
    follow_up_date = db.Column(db.Date)
    customer_visible_note = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    corporate_customer = db.relationship("CorporateCustomer", backref=db.backref("inquiries", lazy="dynamic"))
    owner = db.relationship("User", foreign_keys=[owner_id])
    related_order = db.relationship("Order")

    __table_args__ = (
        db.Index("idx_corporate_inquiry_status_created", "status", "created_at"),
        db.Index("idx_corporate_inquiry_followup", "follow_up_date"),
    )


class CorporateInquiryStatusHistory(db.Model):
    __tablename__ = "corporate_inquiry_status_history"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("corporate_inquiries.id"), nullable=False)
    previous_status = db.Column(db.String(40))
    new_status = db.Column(db.String(40), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    customer_visible_note = db.Column(db.Text)
    internal_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    inquiry = db.relationship("CorporateInquiry", backref=db.backref("status_history", lazy="dynamic"))
    updater = db.relationship("User")


class CorporateQuote(db.Model):
    __tablename__ = "corporate_quotes"
    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("corporate_inquiries.id"), nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(40), default="draft", nullable=False)
    line_items_json = db.Column(db.Text)
    subtotal = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    customization_charges = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    packaging_charges = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    delivery_charges = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    discount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    advance_required = db.Column(db.Numeric(12, 2), default=0)
    payment_terms = db.Column(db.Text)
    validity_date = db.Column(db.Date)
    delivery_schedule = db.Column(db.Text)
    terms = db.Column(db.Text)
    approved_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    inquiry = db.relationship("CorporateInquiry", backref=db.backref("quotes", lazy="dynamic"))
    creator = db.relationship("User")

    __table_args__ = (
        db.Index("idx_corporate_quote_inquiry_version", "inquiry_id", "version"),
    )


class BackupVerification(db.Model):
    __tablename__ = "backup_verifications"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), default="unknown")
    details = db.Column(db.Text)
    verified_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class QueueMetric(db.Model):
    __tablename__ = "queue_metrics"
    id = db.Column(db.Integer, primary_key=True)
    queue_name = db.Column(db.String(80), nullable=False)
    backlog = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    retry_count = db.Column(db.Integer, default=0)
    recorded_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ApiUsageLog(db.Model):
    __tablename__ = "api_usage_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    version = db.Column(db.String(20), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    status_code = db.Column(db.Integer, default=200)
    latency_ms = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", backref="push_devices")


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    email_transactional = db.Column(db.Boolean, default=True, nullable=False)
    sms_transactional = db.Column(db.Boolean, default=True, nullable=False)
    whatsapp_transactional = db.Column(db.Boolean, default=True, nullable=False)
    push_transactional = db.Column(db.Boolean, default=True, nullable=False)
    marketing_email = db.Column(db.Boolean, default=False, nullable=False)
    marketing_sms = db.Column(db.Boolean, default=False, nullable=False)
    marketing_whatsapp = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("notification_preference", uselist=False))


class NotificationTemplate(db.Model):
    __tablename__ = "notification_templates"
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(80), nullable=False)
    channel = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    provider_template_id = db.Column(db.String(120))
    version = db.Column(db.Integer, default=1, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    transactional = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    creator = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("event_type", "channel", "version", name="uq_notification_template_version"),
        db.Index("idx_notification_template_event_channel", "event_type", "channel", "is_active"),
    )


class NotificationDeliveryLog(db.Model):
    __tablename__ = "notification_delivery_logs"
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    event_type = db.Column(db.String(80), nullable=False)
    channel = db.Column(db.String(30), nullable=False)
    recipient_masked = db.Column(db.String(120))
    template_id = db.Column(db.Integer, db.ForeignKey("notification_templates.id"))
    template_version = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(30), default="queued", nullable=False)
    attempt_count = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    provider = db.Column(db.String(60))
    provider_message_id = db.Column(db.String(120))
    idempotency_key = db.Column(db.String(160), unique=True, nullable=False)
    error_details = db.Column(db.Text)
    queued_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    notification = db.relationship("Notification")
    user = db.relationship("User")
    order = db.relationship("Order")
    template = db.relationship("NotificationTemplate")

    __table_args__ = (
        db.Index("idx_notification_delivery_event_status", "event_type", "status", "queued_at"),
        db.Index("idx_notification_delivery_order", "order_id", "event_type"),
    )


class KitchenAlert(db.Model):
    __tablename__ = "kitchen_alerts"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    alert_type = db.Column(db.String(40), default="new_order", nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    priority = db.Column(db.String(20), default="normal", nullable=False)
    payload_json = db.Column(db.Text)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    acknowledged_at = db.Column(db.DateTime)
    print_status = db.Column(db.String(30), default="pending", nullable=False)
    print_attempts = db.Column(db.Integer, default=0, nullable=False)
    last_printed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    order = db.relationship("Order", backref=db.backref("kitchen_alerts", lazy="dynamic"))
    branch = db.relationship("Branch")
    acknowledger = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("order_id", "alert_type", name="uq_kitchen_alert_once"),
        db.Index("idx_kitchen_alert_branch_status", "branch_id", "status", "created_at"),
    )


class DiningArea(db.Model):
    __tablename__ = "dining_areas"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    branch = db.relationship("Branch", backref="dining_areas")

    __table_args__ = (
        db.UniqueConstraint("branch_id", "name", name="uq_dining_area_branch_name"),
    )


class DiningTable(db.Model):
    __tablename__ = "dining_tables"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    area_id = db.Column(db.Integer, db.ForeignKey("dining_areas.id"))
    table_number = db.Column(db.String(40), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    seating_capacity = db.Column(db.Integer, default=2, nullable=False)
    qr_token = db.Column(db.String(96), unique=True, nullable=False)
    status = db.Column(db.String(40), default="active", nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    last_regenerated_at = db.Column(db.DateTime)

    branch = db.relationship("Branch", backref="dining_tables")
    area = db.relationship("DiningArea", backref="tables")

    __table_args__ = (
        db.UniqueConstraint("branch_id", "table_number", name="uq_dining_table_branch_number"),
        db.Index("idx_dining_table_branch_status", "branch_id", "status"),
    )


class TableMenuSession(db.Model):
    __tablename__ = "table_menu_sessions"
    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(96), unique=True, nullable=False)
    table_id = db.Column(db.Integer, db.ForeignKey("dining_tables.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="active", nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    table = db.relationship("DiningTable", backref=db.backref("menu_sessions", lazy="dynamic"))
    branch = db.relationship("Branch")
    user = db.relationship("User")

    __table_args__ = (
        db.Index("idx_table_menu_session_table_status", "table_id", "status", "expires_at"),
    )


class TableMenuScan(db.Model):
    __tablename__ = "table_menu_scans"
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey("dining_tables.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    session_token = db.Column(db.String(96))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    table = db.relationship("DiningTable", backref=db.backref("menu_scans", lazy="dynamic"))
    branch = db.relationship("Branch")

    __table_args__ = (
        db.Index("idx_table_menu_scan_table_created", "table_id", "created_at"),
        db.Index("idx_table_menu_scan_branch_created", "branch_id", "created_at"),
    )


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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)
