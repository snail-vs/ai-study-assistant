"""persist structured course brief and generation scale

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
"""

from alembic import op
import sqlalchemy as sa


revision = "d7e8f9a0b1c2"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learning_spaces", sa.Column("course_brief_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("learning_spaces", sa.Column("course_scale", sa.String(length=20), nullable=False, server_default="standard"))


def downgrade() -> None:
    op.drop_column("learning_spaces", "course_scale")
    op.drop_column("learning_spaces", "course_brief_json")
