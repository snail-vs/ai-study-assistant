"""persist confirmed course outline

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""

from alembic import op
import sqlalchemy as sa

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learning_spaces", sa.Column("course_outline_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("learning_spaces", "course_outline_json")
