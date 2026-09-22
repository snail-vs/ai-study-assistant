"""add recoverable course generation state

Revision ID: 5e6f7a8b9c0d
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa


revision = "5e6f7a8b9c0d"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_cards", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    op.add_column("knowledge_cards", sa.Column("course_plan_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("knowledge_cards", sa.Column("course_quality_report_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("knowledge_cards", sa.Column("generation_version", sa.String(length=50), nullable=False, server_default="v2"))
    op.add_column("card_sections", sa.Column("plan_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("card_sections", sa.Column("actual_summary_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("card_sections", sa.Column("content_blocks_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("card_sections", sa.Column("generation_status", sa.String(length=30), nullable=False, server_default="completed"))
    op.add_column("card_sections", sa.Column("generation_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("card_sections", sa.Column("generation_error", sa.Text(), nullable=True))
    op.add_column("card_sections", sa.Column("generation_metadata_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("card_sections", "generation_metadata_json")
    op.drop_column("card_sections", "generation_error")
    op.drop_column("card_sections", "generation_attempts")
    op.drop_column("card_sections", "generation_status")
    op.drop_column("card_sections", "content_blocks_json")
    op.drop_column("card_sections", "actual_summary_json")
    op.drop_column("card_sections", "plan_json")
    op.drop_column("knowledge_cards", "generation_version")
    op.drop_column("knowledge_cards", "course_quality_report_json")
    op.drop_column("knowledge_cards", "course_plan_json")
    op.drop_column("knowledge_cards", "summary")
