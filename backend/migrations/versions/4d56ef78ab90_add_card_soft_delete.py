"""add soft delete to knowledge cards

Revision ID: 4d56ef78ab90
Revises: 3c45de67fa89
"""

from alembic import op
import sqlalchemy as sa


revision = "4d56ef78ab90"
down_revision = "3c45de67fa89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_cards", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_cards", "deleted_at")
