"""add section teaching metadata

Revision ID: 8f23bc45de67
Revises: 7e12ab34cd56
"""

from alembic import op
import sqlalchemy as sa


revision = "8f23bc45de67"
down_revision = "7e12ab34cd56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "card_sections",
        sa.Column("content_type", sa.String(length=30), nullable=False, server_default="concept"),
    )
    op.add_column("card_sections", sa.Column("teaching_objective", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("card_sections", "teaching_objective")
    op.drop_column("card_sections", "content_type")
