"""index conversations by card and section

Revision ID: f3a4b5c6d7e
Revises: f2a3b4c5d6e7
"""

from alembic import op


revision = "f3a4b5c6d7e"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_card_section_created_at",
        "conversations",
        ["card_id", "section_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_card_section_created_at", table_name="conversations")
