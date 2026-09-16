"""add learning activities and attempts

Revision ID: ab45de67f890
Revises: 9a34cd56ef78
"""

from alembic import op
import sqlalchemy as sa


revision = "ab45de67f890"
down_revision = "9a34cd56ef78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("answer_key_json", sa.Text(), nullable=False),
        sa.Column("generation_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["knowledge_cards.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["card_sections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "activity_type", name="uq_section_activity_type"),
    )
    op.create_table(
        "activity_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("mastery_level", sa.String(length=30), nullable=True),
        sa.Column("diagnostic_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["learning_activities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("activity_attempts")
    op.drop_table("learning_activities")
