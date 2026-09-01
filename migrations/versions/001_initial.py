"""Initial migration - create users and orders tables."""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial tables."""
    # Users table
    op.create_table(
        "users",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    # Orders table
    op.create_table(
        "orders",
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(50), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("drink_name", sa.String(255), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("pickup_time", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(50), server_default="New", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("order_id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"])
    op.create_index("ix_orders_telegram_id", "orders", ["telegram_id"])
    op.create_index("ix_orders_status", "orders", ["status"])


def downgrade() -> None:
    """Drop tables."""
    op.drop_table("orders")
    op.drop_table("users")
