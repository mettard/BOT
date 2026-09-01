"""Add favorite order fields to users table."""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "002_add_user_favorite_order"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add favorite order columns to users table."""
    op.add_column("users", sa.Column("favorite_drink_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("favorite_volume_ml", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("favorite_price", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("favorite_phone", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("favorite_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove favorite order columns from users table."""
    op.drop_column("users", "favorite_notes")
    op.drop_column("users", "favorite_phone")
    op.drop_column("users", "favorite_price")
    op.drop_column("users", "favorite_volume_ml")
    op.drop_column("users", "favorite_drink_name")
