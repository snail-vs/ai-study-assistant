"""add durable leases for asynchronous course generation

Revision ID: 0a12bc34de56
Revises: ff45ab67cd89
"""

from alembic import op
import sqlalchemy as sa


revision = "0a12bc34de56"
down_revision = "ff45ab67cd89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_spaces",
        sa.Column("generation_lease_owner", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "learning_spaces",
        sa.Column("generation_lease_token", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "learning_spaces",
        sa.Column("generation_lease_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("learning_spaces", "generation_lease_expires_at")
    op.drop_column("learning_spaces", "generation_lease_token")
    op.drop_column("learning_spaces", "generation_lease_owner")
