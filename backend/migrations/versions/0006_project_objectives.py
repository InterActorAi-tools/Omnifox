"""campaign objectives on projects

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("objectives", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("projects", "objectives")
