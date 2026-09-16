"""allow activity sourced proposals

Revision ID: bc56ef78a901
Revises: ab45de67f890
"""

from alembic import op
import sqlalchemy as sa


revision = "bc56ef78a901"
down_revision = "ab45de67f890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("related_card_proposals") as batch_op:
        batch_op.alter_column("conversation_id", existing_type=sa.String(length=36), nullable=True)
        batch_op.add_column(sa.Column("activity_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_related_card_proposals_activity_id",
            "learning_activities",
            ["activity_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("related_card_proposals") as batch_op:
        batch_op.drop_constraint("fk_related_card_proposals_activity_id", type_="foreignkey")
        batch_op.drop_column("activity_id")
        batch_op.alter_column("conversation_id", existing_type=sa.String(length=36), nullable=False)
