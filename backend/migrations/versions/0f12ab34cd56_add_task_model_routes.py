"""persist task to model routes

Revision ID: 0f12ab34cd56
Revises: ff45ab67cd89
"""

from alembic import op
import sqlalchemy as sa


revision = "0f12ab34cd56"
down_revision = "ff45ab67cd89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_credentials",
        sa.Column("task_routes_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("provider_credentials", "task_routes_json")
