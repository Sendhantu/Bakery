"""Add security, analytics, notifications, and table QR features.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("session_id", sa.String(120)),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="declined"),
        sa.Column("source", sa.String(40), server_default="web"),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_customer_consent_user_category", "customer_consents", ["user_id", "category", "created_at"])
    op.create_index("idx_customer_consent_session_category", "customer_consents", ["session_id", "category", "created_at"])

    op.create_table(
        "webhook_event_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(120)),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("signature_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("processing_status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("replayed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_details", sa.Text()),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime()),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
    )
    op.create_index("idx_webhook_provider_received", "webhook_event_logs", ["provider", "received_at"])
    op.create_index("idx_webhook_signature_status", "webhook_event_logs", ["signature_status", "received_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("path", sa.String(255)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_security_event_type_created", "security_events", ["event_type", "created_at"])
    op.create_index("idx_security_event_severity_created", "security_events", ["severity", "created_at"])

    op.create_table(
        "dining_areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("branch_id", "name", name="uq_dining_area_branch_name"),
    )
    op.create_table(
        "dining_tables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("dining_areas.id")),
        sa.Column("table_number", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("seating_capacity", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("qr_token", sa.String(96), nullable=False, unique=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("last_regenerated_at", sa.DateTime()),
        sa.UniqueConstraint("branch_id", "table_number", name="uq_dining_table_branch_number"),
    )
    op.create_index("idx_dining_table_branch_status", "dining_tables", ["branch_id", "status"])
    op.create_table(
        "table_menu_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_token", sa.String(96), nullable=False, unique=True),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("dining_tables.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_table_menu_session_table_status", "table_menu_sessions", ["table_id", "status", "expires_at"])
    op.create_table(
        "table_menu_scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("dining_tables.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("session_token", sa.String(96)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_table_menu_scan_table_created", "table_menu_scans", ["table_id", "created_at"])
    op.create_index("idx_table_menu_scan_branch_created", "table_menu_scans", ["branch_id", "created_at"])

    op.create_table(
        "conversion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(80), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("session_id", sa.String(120)),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("path", sa.String(255)),
        sa.Column("source", sa.String(80)),
        sa.Column("medium", sa.String(80)),
        sa.Column("campaign", sa.String(120)),
        sa.Column("content", sa.String(120)),
        sa.Column("term", sa.String(120)),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("dining_tables.id")),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("amount", sa.Numeric(10, 2), server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_conversion_event_name_created", "conversion_events", ["event_name", "created_at"])
    op.create_index("idx_conversion_branch_created", "conversion_events", ["branch_id", "created_at"])
    op.create_index("idx_conversion_product_created", "conversion_events", ["product_id", "created_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("email_transactional", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sms_transactional", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("whatsapp_transactional", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("push_transactional", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("marketing_email", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marketing_sms", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marketing_whatsapp", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("subject", sa.String(200)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_template_id", sa.String(120)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transactional", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("event_type", "channel", "version", name="uq_notification_template_version"),
    )
    op.create_index("idx_notification_template_event_channel", "notification_templates", ["event_type", "channel", "is_active"])
    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("recipient_masked", sa.String(120)),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("notification_templates.id")),
        sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("provider", sa.String(60)),
        sa.Column("provider_message_id", sa.String(120)),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("error_details", sa.Text()),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("delivered_at", sa.DateTime()),
        sa.Column("cancelled_at", sa.DateTime()),
    )
    op.create_index("idx_notification_delivery_event_status", "notification_delivery_logs", ["event_type", "status", "queued_at"])
    op.create_index("idx_notification_delivery_order", "notification_delivery_logs", ["order_id", "event_type"])
    op.create_table(
        "kitchen_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("alert_type", sa.String(40), nullable=False, server_default="new_order"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("payload_json", sa.Text()),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("acknowledged_at", sa.DateTime()),
        sa.Column("print_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("print_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_printed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("order_id", "alert_type", name="uq_kitchen_alert_once"),
    )
    op.create_index("idx_kitchen_alert_branch_status", "kitchen_alerts", ["branch_id", "status", "created_at"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("dining_table_id", sa.Integer(), sa.ForeignKey("dining_tables.id")))
        batch.add_column(sa.Column("table_session_id", sa.Integer(), sa.ForeignKey("table_menu_sessions.id")))
        batch.add_column(sa.Column("dine_in_payment_timing", sa.String(40)))


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("dine_in_payment_timing")
        batch.drop_column("table_session_id")
        batch.drop_column("dining_table_id")
    op.drop_index("idx_kitchen_alert_branch_status", table_name="kitchen_alerts")
    op.drop_table("kitchen_alerts")
    op.drop_index("idx_notification_delivery_order", table_name="notification_delivery_logs")
    op.drop_index("idx_notification_delivery_event_status", table_name="notification_delivery_logs")
    op.drop_table("notification_delivery_logs")
    op.drop_index("idx_notification_template_event_channel", table_name="notification_templates")
    op.drop_table("notification_templates")
    op.drop_table("notification_preferences")
    op.drop_index("idx_conversion_product_created", table_name="conversion_events")
    op.drop_index("idx_conversion_branch_created", table_name="conversion_events")
    op.drop_index("idx_conversion_event_name_created", table_name="conversion_events")
    op.drop_table("conversion_events")
    op.drop_index("idx_table_menu_scan_branch_created", table_name="table_menu_scans")
    op.drop_index("idx_table_menu_scan_table_created", table_name="table_menu_scans")
    op.drop_table("table_menu_scans")
    op.drop_index("idx_table_menu_session_table_status", table_name="table_menu_sessions")
    op.drop_table("table_menu_sessions")
    op.drop_index("idx_dining_table_branch_status", table_name="dining_tables")
    op.drop_table("dining_tables")
    op.drop_table("dining_areas")
    op.drop_index("idx_security_event_severity_created", table_name="security_events")
    op.drop_index("idx_security_event_type_created", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("idx_webhook_signature_status", table_name="webhook_event_logs")
    op.drop_index("idx_webhook_provider_received", table_name="webhook_event_logs")
    op.drop_table("webhook_event_logs")
    op.drop_index("idx_customer_consent_session_category", table_name="customer_consents")
    op.drop_index("idx_customer_consent_user_category", table_name="customer_consents")
    op.drop_table("customer_consents")
