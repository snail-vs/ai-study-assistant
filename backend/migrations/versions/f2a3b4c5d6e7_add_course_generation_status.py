"""persist asynchronous course generation status

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_spaces",
        sa.Column("generation_status", sa.String(length=20), nullable=False, server_default="completed"),
    )
    op.add_column(
        "learning_spaces",
        sa.Column("generation_phase", sa.String(length=30), nullable=False, server_default="completed"),
    )
    op.add_column("learning_spaces", sa.Column("generation_error", sa.Text(), nullable=True))
    op.add_column(
        "learning_spaces",
        sa.Column("generation_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("learning_spaces", "generation_updated_at")
    op.drop_column("learning_spaces", "generation_error")
    op.drop_column("learning_spaces", "generation_phase")
    op.drop_column("learning_spaces", "generation_status")
