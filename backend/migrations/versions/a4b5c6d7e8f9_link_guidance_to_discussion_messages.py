"""link teacher guidance to source discussion messages

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e
"""

from alembic import op
import sqlalchemy as sa


revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teacher_guidance", sa.Column("source_question_message_id", sa.String(length=36), nullable=True))
    op.add_column("teacher_guidance", sa.Column("source_answer_message_id", sa.String(length=36), nullable=True))
    op.add_column("teacher_guidance", sa.Column("source_question", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("teacher_guidance", "source_question")
    op.drop_column("teacher_guidance", "source_answer_message_id")
    op.drop_column("teacher_guidance", "source_question_message_id")
