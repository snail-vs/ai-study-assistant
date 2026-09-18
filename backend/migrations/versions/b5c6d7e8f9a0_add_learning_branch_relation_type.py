"""classify prerequisite and extension learning branches

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""

from alembic import op
import sqlalchemy as sa


revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_cards", sa.Column("relation_type", sa.String(length=30), nullable=True))
    op.add_column(
        "related_card_proposals",
        sa.Column("relation_type", sa.String(length=30), nullable=False, server_default="prerequisite"),
    )


def downgrade() -> None:
    op.drop_column("related_card_proposals", "relation_type")
    op.drop_column("knowledge_cards", "relation_type")
