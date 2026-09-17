"""add oauth fields to provider credentials

Revision ID: c7d8e9fa01ab
Revises: bc56ef78a901
Create Date: 2026-09-17 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9fa01ab"
down_revision: Union[str, None] = "bc56ef78a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.add_column(
            sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="api_key")
        )
        batch_op.add_column(sa.Column("oauth_access_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("oauth_access_nonce", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("oauth_refresh_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("oauth_refresh_nonce", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("oauth_expires_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("oauth_account_id", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.drop_column("oauth_account_id")
        batch_op.drop_column("oauth_expires_at")
        batch_op.drop_column("oauth_refresh_nonce")
        batch_op.drop_column("oauth_refresh_ciphertext")
        batch_op.drop_column("oauth_access_nonce")
        batch_op.drop_column("oauth_access_ciphertext")
        batch_op.drop_column("auth_type")
