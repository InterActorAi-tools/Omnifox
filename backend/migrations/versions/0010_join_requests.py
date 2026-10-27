"""requests to join without an invitation

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "join_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_join_requests_id", "join_requests", ["id"])
    op.create_index("ix_join_requests_email", "join_requests", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_join_requests_email", table_name="join_requests")
    op.drop_index("ix_join_requests_id", table_name="join_requests")
    op.drop_table("join_requests")
