"""Add delivery serviceability, tracking, reminders, and corporate workflows.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_zone_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), unique=True),
        sa.Column("max_radius_km", sa.Numeric(8, 2), nullable=False, server_default="7"),
        sa.Column("free_radius_km", sa.Numeric(8, 2), nullable=False, server_default="3"),
        sa.Column("min_order_value", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("extra_fee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("is_delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_pickup_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("availability_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "delivery_distance_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("min_distance_km", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("max_distance_km", sa.Numeric(8, 2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_delivery_band_branch_distance",
        "delivery_distance_bands",
        ["branch_id", "min_distance_km", "max_distance_km"],
    )
    op.create_table(
        "delivery_pincode_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("pincode", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="supported"),
        sa.Column("delivery_fee_override", sa.Numeric(10, 2)),
        sa.Column("estimated_delivery_minutes", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("branch_id", "pincode", name="uq_delivery_pincode_branch"),
    )
    op.create_index("idx_delivery_pincode_status", "delivery_pincode_rules", ["pincode", "status"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("tracking_token", sa.String(80)))
        batch.add_column(sa.Column("estimated_ready_at", sa.DateTime()))
        batch.add_column(sa.Column("status_note", sa.Text()))
        batch.add_column(sa.Column("delay_reason", sa.Text()))
        batch.add_column(sa.Column("delayed_until", sa.DateTime()))
        batch.add_column(sa.Column("serviceability_status", sa.String(30)))
        batch.add_column(sa.Column("serviceability_message", sa.String(255)))
        batch.add_column(sa.Column("serviceability_distance_km", sa.Numeric(8, 2)))
        batch.add_column(sa.Column("serviceability_rule_source", sa.String(40)))
        batch.add_column(sa.Column("b2b_company_name", sa.String(160)))
        batch.add_column(sa.Column("b2b_gstin", sa.String(15)))
        batch.add_column(sa.Column("b2b_billing_address", sa.Text()))
        batch.add_column(sa.Column("b2b_state", sa.String(80)))
        batch.add_column(sa.Column("b2b_pincode", sa.String(10)))
        batch.add_column(sa.Column("b2b_po_number", sa.String(80)))
        batch.add_column(sa.Column("b2b_department", sa.String(120)))
        batch.add_column(sa.Column("b2b_billing_email", sa.String(120)))
        batch.add_column(sa.Column("b2b_contact_person", sa.String(120)))
        batch.add_column(sa.Column("b2b_invoice_notes", sa.Text()))
        batch.create_unique_constraint("uq_orders_tracking_token", ["tracking_token"])

    op.create_table(
        "order_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("previous_status", sa.String(30)),
        sa.Column("new_status", sa.String(30), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("update_source", sa.String(40), nullable=False, server_default="system"),
        sa.Column("customer_note", sa.Text()),
        sa.Column("internal_note", sa.Text()),
        sa.Column("related_employee_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("delivery_agent_id", sa.Integer(), sa.ForeignKey("delivery_agents.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_order_status_history_order_created", "order_status_history", ["order_id", "created_at"])
    op.create_index("idx_order_status_history_status", "order_status_history", ["new_status"])
    op.create_table(
        "order_status_notification_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False, server_default="in_app"),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("delivery_status", sa.String(30), nullable=False, server_default="sent"),
        sa.Column("template", sa.String(80)),
        sa.Column("error_details", sa.Text()),
        sa.UniqueConstraint("order_id", "status", "channel", name="uq_order_status_notification_once"),
    )
    op.create_index("idx_order_status_notification_order", "order_status_notification_logs", ["order_id", "sent_at"])

    with op.batch_alter_table("recurring_subscriptions") as batch:
        batch.add_column(sa.Column("fulfillment_type", sa.String(20), nullable=False, server_default="DELIVERY"))
        batch.add_column(sa.Column("saved_address_id", sa.Integer(), sa.ForeignKey("saved_addresses.id")))

    op.create_table(
        "occasion_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("occasion_type", sa.String(60), nullable=False),
        sa.Column("occasion_date", sa.Date(), nullable=False),
        sa.Column("recipient_name", sa.String(120)),
        sa.Column("relationship", sa.String(80)),
        sa.Column("preferred_channel", sa.String(30), nullable=False, server_default="email"),
        sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recommendations_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("idx_occasion_user_active", "occasion_reminders", ["user_id", "is_active"])
    op.create_index("idx_occasion_date", "occasion_reminders", ["occasion_date"])
    op.create_table(
        "occasion_reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reminder_id", sa.Integer(), sa.ForeignKey("occasion_reminders.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("occasion_year", sa.Integer(), nullable=False),
        sa.Column("campaign", sa.String(80), nullable=False, server_default="annual_occasion"),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="sent"),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id")),
        sa.Column("message", sa.Text()),
        sa.Column("error_details", sa.Text()),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reminder_id", "occasion_year", "campaign", "channel", name="uq_occasion_reminder_once_per_year"),
    )

    op.create_table(
        "corporate_customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_name", sa.String(180), nullable=False),
        sa.Column("gstin", sa.String(15)),
        sa.Column("billing_address", sa.Text()),
        sa.Column("delivery_locations_json", sa.Text()),
        sa.Column("contact_persons_json", sa.Text()),
        sa.Column("approved_payment_terms", sa.String(120)),
        sa.Column("credit_limit", sa.Numeric(12, 2), server_default="0"),
        sa.Column("outstanding_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("preferred_products_json", sa.Text()),
        sa.Column("contract_pricing_json", sa.Text()),
        sa.Column("account_manager_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("internal_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_table(
        "corporate_inquiries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("corporate_customer_id", sa.Integer(), sa.ForeignKey("corporate_customers.id")),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("related_order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("status", sa.String(40), nullable=False, server_default="new"),
        sa.Column("contact_name", sa.String(120), nullable=False),
        sa.Column("company_name", sa.String(180), nullable=False),
        sa.Column("work_email", sa.String(120), nullable=False),
        sa.Column("mobile", sa.String(30), nullable=False),
        sa.Column("gstin", sa.String(15)),
        sa.Column("billing_address", sa.Text()),
        sa.Column("delivery_location", sa.Text(), nullable=False),
        sa.Column("required_date", sa.Date(), nullable=False),
        sa.Column("preferred_delivery_time", sa.String(50)),
        sa.Column("people_count", sa.Integer()),
        sa.Column("estimated_quantity", sa.Integer()),
        sa.Column("budget_range", sa.String(80)),
        sa.Column("products_required", sa.Text()),
        sa.Column("custom_branding", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dietary_requirements", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("attachment_filename", sa.String(255)),
        sa.Column("attachment_path", sa.String(500)),
        sa.Column("follow_up_date", sa.Date()),
        sa.Column("customer_visible_note", sa.Text()),
        sa.Column("internal_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("idx_corporate_inquiry_status_created", "corporate_inquiries", ["status", "created_at"])
    op.create_index("idx_corporate_inquiry_followup", "corporate_inquiries", ["follow_up_date"])
    op.create_table(
        "corporate_inquiry_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("corporate_inquiries.id"), nullable=False),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("customer_visible_note", sa.Text()),
        sa.Column("internal_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "corporate_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("corporate_inquiries.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("line_items_json", sa.Text()),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("customization_charges", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("packaging_charges", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("delivery_charges", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("advance_required", sa.Numeric(12, 2), server_default="0"),
        sa.Column("payment_terms", sa.Text()),
        sa.Column("validity_date", sa.Date()),
        sa.Column("delivery_schedule", sa.Text()),
        sa.Column("terms", sa.Text()),
        sa.Column("approved_at", sa.DateTime()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_corporate_quote_inquiry_version", "corporate_quotes", ["inquiry_id", "version"])


def downgrade():
    op.drop_index("idx_corporate_quote_inquiry_version", table_name="corporate_quotes")
    op.drop_table("corporate_quotes")
    op.drop_table("corporate_inquiry_status_history")
    op.drop_index("idx_corporate_inquiry_followup", table_name="corporate_inquiries")
    op.drop_index("idx_corporate_inquiry_status_created", table_name="corporate_inquiries")
    op.drop_table("corporate_inquiries")
    op.drop_table("corporate_customers")
    op.drop_table("occasion_reminder_logs")
    op.drop_index("idx_occasion_date", table_name="occasion_reminders")
    op.drop_index("idx_occasion_user_active", table_name="occasion_reminders")
    op.drop_table("occasion_reminders")
    with op.batch_alter_table("recurring_subscriptions") as batch:
        batch.drop_column("saved_address_id")
        batch.drop_column("fulfillment_type")
    op.drop_index("idx_order_status_notification_order", table_name="order_status_notification_logs")
    op.drop_table("order_status_notification_logs")
    op.drop_index("idx_order_status_history_status", table_name="order_status_history")
    op.drop_index("idx_order_status_history_order_created", table_name="order_status_history")
    op.drop_table("order_status_history")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("uq_orders_tracking_token", type_="unique")
        for column in [
            "b2b_invoice_notes",
            "b2b_contact_person",
            "b2b_billing_email",
            "b2b_department",
            "b2b_po_number",
            "b2b_pincode",
            "b2b_state",
            "b2b_billing_address",
            "b2b_gstin",
            "b2b_company_name",
            "serviceability_rule_source",
            "serviceability_distance_km",
            "serviceability_message",
            "serviceability_status",
            "delayed_until",
            "delay_reason",
            "status_note",
            "estimated_ready_at",
            "tracking_token",
        ]:
            batch.drop_column(column)
    op.drop_index("idx_delivery_pincode_status", table_name="delivery_pincode_rules")
    op.drop_table("delivery_pincode_rules")
    op.drop_index("idx_delivery_band_branch_distance", table_name="delivery_distance_bands")
    op.drop_table("delivery_distance_bands")
    op.drop_table("delivery_zone_settings")
