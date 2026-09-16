"""persist global default model

Revision ID: 2b34cd56ef78
Revises: 1a23bc45de67
"""

from alembic import op
import sqlalchemy as sa


revision = "2b34cd56ef78"
down_revision = "1a23bc45de67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "default_model_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("default_model_preferences")
