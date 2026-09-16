"""persist global task model routes

Revision ID: 1a23bc45de67
Revises: 0f12ab34cd56
"""

from alembic import op
import sqlalchemy as sa


revision = "1a23bc45de67"
down_revision = "0f12ab34cd56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_model_routes",
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("task"),
    )


def downgrade() -> None:
    op.drop_table("task_model_routes")
