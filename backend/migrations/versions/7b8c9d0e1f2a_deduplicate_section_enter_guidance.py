"""deduplicate section-enter guidance

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
"""

from alembic import op
import sqlalchemy as sa


revision = "7b8c9d0e1f2a"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the oldest completed intro if historical races already created duplicates.
    op.execute(sa.text("""
        DELETE FROM teacher_guidance
        WHERE trigger = 'section_enter'
          AND id IN (
            SELECT duplicate.id
            FROM teacher_guidance AS duplicate
            JOIN teacher_guidance AS keeper
              ON keeper.card_id = duplicate.card_id
             AND keeper.section_id = duplicate.section_id
             AND keeper.trigger = 'section_enter'
             AND (
               keeper.created_at < duplicate.created_at
               OR (keeper.created_at = duplicate.created_at AND keeper.id < duplicate.id)
             )
          )
    """))
    op.create_index(
        "uq_teacher_guidance_section_enter",
        "teacher_guidance",
        ["card_id", "section_id"],
        unique=True,
        sqlite_where=sa.text("trigger = 'section_enter'"),
        postgresql_where=sa.text("trigger = 'section_enter'"),
    )


def downgrade() -> None:
    op.drop_index("uq_teacher_guidance_section_enter", table_name="teacher_guidance")
