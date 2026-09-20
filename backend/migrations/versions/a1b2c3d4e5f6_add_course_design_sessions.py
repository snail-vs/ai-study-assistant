"""persist guided course design sessions"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_design_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_learning_space_id", sa.String(length=36), sa.ForeignKey("learning_spaces.id"), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="collecting_goals"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("brief_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("brief_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("current_question_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("questions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("recommended_scale", sa.String(length=20), nullable=True),
        sa.Column("selected_scale", sa.String(length=20), nullable=True),
        sa.Column("outline_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("outline_basis_brief_revision", sa.Integer(), nullable=True),
        sa.Column("outline_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("processed_commands_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("operation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("outline_revision_messages_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_course_design_sessions_user_id", "course_design_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_course_design_sessions_user_id", table_name="course_design_sessions")
    op.drop_table("course_design_sessions")
