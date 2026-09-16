"""add learning runtime

Revision ID: 9a34cd56ef78
Revises: 8f23bc45de67
"""

from alembic import op
import sqlalchemy as sa


revision = "9a34cd56ef78"
down_revision = "8f23bc45de67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_runtimes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("current_card_id", sa.String(length=36), nullable=True),
        sa.Column("current_section_id", sa.String(length=36), nullable=True),
        sa.Column("source_card_id", sa.String(length=36), nullable=True),
        sa.Column("source_section_id", sa.String(length=36), nullable=True),
        sa.Column("navigation_stack_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["space_id"], ["learning_spaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("space_id"),
    )
    op.create_table(
        "learning_runtime_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("runtime_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=True),
        sa.Column("section_id", sa.String(length=36), nullable=True),
        sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["runtime_id"], ["learning_runtimes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runtime_id", "seq", name="uq_learning_runtime_record_seq"),
    )


def downgrade() -> None:
    op.drop_table("learning_runtime_records")
    op.drop_table("learning_runtimes")
