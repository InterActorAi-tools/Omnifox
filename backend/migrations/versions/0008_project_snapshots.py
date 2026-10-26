"""stats of each upload to a project, for its trends

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=True),
        sa.Column("stats", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_snapshots_project_id", "project_snapshots", ["project_id"])
    op.create_index("ix_project_snapshots_task_id", "project_snapshots", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_project_snapshots_task_id", table_name="project_snapshots")
    op.drop_index("ix_project_snapshots_project_id", table_name="project_snapshots")
    op.drop_table("project_snapshots")
