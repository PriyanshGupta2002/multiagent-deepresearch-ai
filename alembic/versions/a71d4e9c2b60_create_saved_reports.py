"""create saved reports

Revision ID: a71d4e9c2b60
Revises: 854312a4c793
Create Date: 2026-11-05 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a71d4e9c2b60"
down_revision: Union[str, Sequence[str], None] = "854312a4c793"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("research_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["research_id"], ["research_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "research_id",
            name="uq_saved_reports_user_research",
        ),
    )
    op.create_index(
        "ix_saved_reports_user_created_at",
        "saved_reports",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_saved_reports_research_id",
        "saved_reports",
        ["research_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_reports_research_id", table_name="saved_reports")
    op.drop_index("ix_saved_reports_user_created_at", table_name="saved_reports")
    op.drop_table("saved_reports")
