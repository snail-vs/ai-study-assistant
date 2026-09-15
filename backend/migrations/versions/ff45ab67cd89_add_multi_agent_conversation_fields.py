"""add multi-agent conversation fields

Revision ID: ff45ab67cd89
Revises: ee34fa56ab78
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ff45ab67cd89"
down_revision: Union[str, None] = "ee34fa56ab78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("mode", sa.String(length=20), nullable=True, server_default="single"))
    op.add_column("conversations", sa.Column("participant_ids_json", sa.Text(), nullable=True, server_default="[]"))
    op.add_column("conversations", sa.Column("trigger_agent_id", sa.String(length=50), nullable=True))
    op.add_column("conversations", sa.Column("director_policy", sa.String(length=30), nullable=True, server_default="guided"))
    op.add_column("messages", sa.Column("sender_id", sa.String(length=50), nullable=True))
    op.add_column("messages", sa.Column("sender_name", sa.String(length=100), nullable=True))
    op.add_column("messages", sa.Column("sender_role", sa.String(length=30), nullable=True))
    op.add_column("messages", sa.Column("visibility", sa.String(length=20), nullable=True, server_default="user"))
    op.execute(sa.text("UPDATE conversations SET mode = 'single', director_policy = 'guided'"))
    op.execute(sa.text("UPDATE conversations SET participant_ids_json = '[\"teacher\"]' WHERE conversation_type = 'main'"))
    op.execute(sa.text("UPDATE conversations SET participant_ids_json = '[\"side_tutor\"]' WHERE conversation_type = 'side'"))
    op.execute(sa.text("UPDATE messages SET visibility = 'user' WHERE visibility IS NULL"))


def downgrade() -> None:
    op.drop_column("messages", "visibility")
    op.drop_column("messages", "sender_role")
    op.drop_column("messages", "sender_name")
    op.drop_column("messages", "sender_id")
    op.drop_column("conversations", "director_policy")
    op.drop_column("conversations", "trigger_agent_id")
    op.drop_column("conversations", "participant_ids_json")
    op.drop_column("conversations", "mode")
