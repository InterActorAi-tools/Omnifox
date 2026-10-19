"""indexes for per-user queries; tz-aware activity_logs.created_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12

- activity_logs (user_id, created_at): every activity query filters by
  user and sorts by time.
- refresh_tokens (user_id): session lists, logout-all, password reset.
- activity_logs.created_at was a naive timestamp while every other
  table is timezone-aware. Existing values were written with
  datetime.utcnow(), so they are interpreted as UTC.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_activity_logs_user_id_created_at", "activity_logs", ["user_id", "created_at"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "activity_logs", "created_at",
            type_=sa.DateTime(timezone=True),
            postgresql_using="created_at AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "activity_logs", "created_at",
            type_=sa.DateTime(),
            postgresql_using="created_at AT TIME ZONE 'UTC'",
        )
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_activity_logs_user_id_created_at", table_name="activity_logs")
