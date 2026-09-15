"""persist encrypted provider credentials

Revision ID: ab12cd34ef56
Revises: 65d07f1027b6
Create Date: 2026-09-15 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ab12cd34ef56"
down_revision: Union[str, None] = "65d07f1027b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_nonce", sa.String(length=50), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("models_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("active_model", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("provider_name"),
    )


def downgrade() -> None:
    op.drop_table("provider_credentials")
