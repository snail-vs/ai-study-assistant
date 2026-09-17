"""merge auth and oauth migration branches

Revision ID: d9e0f1a2b3c4
Revises: cf67ab89de01, c7d8e9fa01ab
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = ("cf67ab89de01", "c7d8e9fa01ab")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OAUTH_COLUMNS = {
    "auth_type": sa.Column(
        "auth_type", sa.String(length=20), nullable=False, server_default="api_key"
    ),
    "oauth_access_ciphertext": sa.Column("oauth_access_ciphertext", sa.Text(), nullable=True),
    "oauth_access_nonce": sa.Column("oauth_access_nonce", sa.String(length=50), nullable=True),
    "oauth_refresh_ciphertext": sa.Column("oauth_refresh_ciphertext", sa.Text(), nullable=True),
    "oauth_refresh_nonce": sa.Column("oauth_refresh_nonce", sa.String(length=50), nullable=True),
    "oauth_expires_at": sa.Column("oauth_expires_at", sa.BigInteger(), nullable=True),
    "oauth_account_id": sa.Column("oauth_account_id", sa.String(length=200), nullable=True),
}


def upgrade() -> None:
    # The auth migration rebuilds provider_credentials and therefore can remove
    # columns added by the OAuth branch when both branches are upgraded. Make
    # the merge revision the single source of truth for the final shape.
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("provider_credentials")}
    missing = [column for name, column in OAUTH_COLUMNS.items() if name not in existing]
    if missing:
        with op.batch_alter_table("provider_credentials") as batch_op:
            for column in missing:
                batch_op.add_column(column)


def downgrade() -> None:
    # These columns belong to the OAuth branch. Keeping them when downgrading
    # the merge revision preserves the c7d8e9fa01ab parent schema.
    pass
