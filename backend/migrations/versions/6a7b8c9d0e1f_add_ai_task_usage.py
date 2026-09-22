"""add prompt-free AI task usage records

Revision ID: 6a7b8c9d0e1f
Revises: f3a4b5c6d7e, 5e6f7a8b9c0d
"""

from alembic import op
import sqlalchemy as sa

revision = "6a7b8c9d0e1f"
down_revision = ("f3a4b5c6d7e", "5e6f7a8b9c0d")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ai_task_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_task_usage_user_id", "ai_task_usage", ["user_id"])
    op.create_index("ix_ai_task_usage_task", "ai_task_usage", ["task"])
    op.create_index("ix_ai_task_usage_created_at", "ai_task_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_task_usage_created_at", table_name="ai_task_usage")
    op.drop_index("ix_ai_task_usage_task", table_name="ai_task_usage")
    op.drop_index("ix_ai_task_usage_user_id", table_name="ai_task_usage")
    op.drop_table("ai_task_usage")
