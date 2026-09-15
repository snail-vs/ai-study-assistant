"""add teacher guidance records

Revision ID: ee34fa56ab78
Revises: cd23ef45ab67
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ee34fa56ab78"
down_revision: Union[str, None] = "cd23ef45ab67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teacher_guidance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=True),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["knowledge_cards.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["card_sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("teacher_guidance")
