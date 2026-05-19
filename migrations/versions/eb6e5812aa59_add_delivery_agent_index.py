"""add_delivery_agent_index

Revision ID: eb6e5812aa59
Revises: 446cba401573
Create Date: 2026-05-19 08:43:58.187787

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eb6e5812aa59'
down_revision = '446cba401573'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("idx_deliveries_agent_id", "deliveries", ["agent_id"], unique=False)
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("items_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_index("idx_deliveries_agent_id", table_name="deliveries")
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("items_json")
