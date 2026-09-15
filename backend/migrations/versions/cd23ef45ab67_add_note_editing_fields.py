"""add note title and updated timestamp

Revision ID: cd23ef45ab67
Revises: ab12cd34ef56
Create Date: 2026-09-15 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cd23ef45ab67"
down_revision: Union[str, None] = "ab12cd34ef56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("notes", sa.Column("updated_at", sa.DateTime(), nullable=True))
    notes = sa.table("notes", sa.column("title", sa.String), sa.column("updated_at", sa.DateTime))
    op.execute(notes.update().values(title="未命名笔记", updated_at=sa.func.current_timestamp()))
    with op.batch_alter_table("notes") as batch_op:
        batch_op.alter_column("title", nullable=False, server_default="未命名笔记")
        batch_op.alter_column("updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("notes", "updated_at")
    op.drop_column("notes", "title")
