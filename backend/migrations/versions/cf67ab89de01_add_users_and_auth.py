"""add users, invite codes, sessions and ownership

Revision ID: cf67ab89de01
Revises: bc56ef78a901
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "cf67ab89de01"
down_revision = "bc56ef78a901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("token_hash"),
    )

    # Existing records are assigned to a non-login legacy owner. The first
    # registered user claims this owner in the auth API.
    legacy_id = "00000000-0000-0000-0000-000000000001"
    op.bulk_insert(
        sa.table(
            "users",
            sa.column("id", sa.String),
            sa.column("username", sa.String),
            sa.column("password_hash", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime),
        ),
        [{"id": legacy_id, "username": "__legacy__", "password_hash": "!bootstrap-required!", "is_active": False, "created_at": datetime.utcnow()}],
    )

    with op.batch_alter_table("learning_spaces") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_learning_spaces_user_id", "users", ["user_id"], ["id"])
    op.execute(sa.text("UPDATE learning_spaces SET user_id = :id WHERE user_id IS NULL").bindparams(id=legacy_id))
    with op.batch_alter_table("learning_spaces") as batch:
        batch.alter_column("user_id", nullable=False)

    # Rebuild the three previously global settings tables with user-scoped keys.
    op.create_table(
        "provider_credentials_new",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_nonce", sa.String(50), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("models_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("active_model", sa.String(200)),
        sa.Column("task_routes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "provider_name"),
    )
    op.execute(sa.text("INSERT INTO provider_credentials_new (user_id, provider_name, api_key_ciphertext, api_key_nonce, encryption_key_version, models_json, active_model, task_routes_json, is_active, created_at, updated_at) SELECT :id, provider_name, api_key_ciphertext, api_key_nonce, encryption_key_version, models_json, active_model, '{}', is_active, created_at, updated_at FROM provider_credentials").bindparams(id=legacy_id))
    op.drop_table("provider_credentials")
    op.rename_table("provider_credentials_new", "provider_credentials")

    op.create_table(
        "task_model_routes_new",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("task", sa.String(80), nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "task"),
    )
    op.execute(sa.text("INSERT INTO task_model_routes_new (user_id, task, provider_name, model_id, updated_at) SELECT :id, task, provider_name, model_id, updated_at FROM task_model_routes").bindparams(id=legacy_id))
    op.drop_table("task_model_routes")
    op.rename_table("task_model_routes_new", "task_model_routes")

    with op.batch_alter_table("default_model_preferences") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_default_model_preferences_user_id", "users", ["user_id"], ["id"])
    op.execute(sa.text("UPDATE default_model_preferences SET user_id = :id WHERE user_id IS NULL").bindparams(id=legacy_id))
    with op.batch_alter_table("default_model_preferences") as batch:
        batch.alter_column("user_id", nullable=False)
        batch.create_unique_constraint("uq_default_model_preferences_user_id", ["user_id"])


def downgrade() -> None:
    raise NotImplementedError("User ownership migration is intentionally irreversible")
