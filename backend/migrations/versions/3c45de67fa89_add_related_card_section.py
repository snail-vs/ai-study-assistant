"""anchor related cards to a source section

Revision ID: 3c45de67fa89
Revises: 2b34cd56ef78
"""

from alembic import op
import sqlalchemy as sa


revision = "3c45de67fa89"
down_revision = "2b34cd56ef78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_cards", sa.Column("parent_section_id", sa.String(length=36), nullable=True))
    op.execute(
        sa.text(
            """UPDATE knowledge_cards
               SET parent_section_id = (
                   SELECT section_id FROM conversations
                   WHERE conversations.id = knowledge_cards.source_conversation_id
               )
             WHERE card_type = 'related'
               AND source_conversation_id IS NOT NULL"""
        )
    )


def downgrade() -> None:
    op.drop_column("knowledge_cards", "parent_section_id")
