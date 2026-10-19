"""encrypt personal data at rest; per-user URL cache

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13

- Columns holding personal data become text and their existing values
  are encrypted with DATA_ENCRYPTION_KEY (see utils/crypto.py).
- Rows already past retention (tasks 30 days, activity logs 365) are
  deleted first; the rest are encrypted in batches of 500.
- url_cache gets an owner (client_id) so one user's results are never
  served to another. Existing entries cannot be attributed to an owner,
  so they are cleared; the cache only holds 24-hour copies.
"""
from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

BATCH = 500

# table -> (primary key, columns to encrypt)
ENCRYPTED = {
    "tasks": ("task_id", ["message", "metadata_json", "result_data"]),
    "url_cache": ("url_hash", ["url", "sentiment_data"]),
    "activity_logs": ("id", ["ip_address", "user_agent", "extra_data"]),
    "refresh_tokens": ("id", ["device_name", "ip_address", "user_agent"]),
    "users": ("id", ["two_factor_secret"]),
}


def upgrade() -> None:
    from utils.crypto import encrypt, is_encrypted

    bind = op.get_bind()
    # Rows past the retention policy would be deleted minutes after start-up
    # anyway (services/privacy.py); dropping them first keeps this migration short.
    now = datetime.now(timezone.utc)
    bind.execute(sa.text("DELETE FROM tasks WHERE created_at < :cutoff"), {"cutoff": now - timedelta(days=30)})
    bind.execute(sa.text("DELETE FROM activity_logs WHERE created_at < :cutoff"), {"cutoff": now - timedelta(days=365)})
    op.execute("DELETE FROM url_cache")
    with op.batch_alter_table("url_cache") as batch:
        batch.add_column(sa.Column("client_id", sa.String(255), nullable=False))
        batch.create_index("ix_url_cache_client_id", ["client_id"])

    for table, (pk, columns) in ENCRYPTED.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, type_=sa.Text(), postgresql_using=f"{column}::text")

        # In batches by primary key, so memory stays flat on large tables.
        last = None
        while True:
            where = f"WHERE {pk} > :last " if last is not None else ""
            rows = bind.execute(sa.text(
                f"SELECT {pk}, {', '.join(columns)} FROM {table} {where}ORDER BY {pk} LIMIT {BATCH}"),
                {"last": last}).fetchall()
            if not rows:
                break
            for row in rows:
                values = {
                    column: encrypt(str(value).encode()).decode()
                    for column, value in zip(columns, row[1:])
                    if value is not None and not is_encrypted(str(value).encode())
                }
                if values:
                    assignments = ", ".join(f"{c} = :{c}" for c in values)
                    bind.execute(sa.text(f"UPDATE {table} SET {assignments} WHERE {pk} = :pk"), {**values, "pk": row[0]})
            last = rows[-1][0]


def downgrade() -> None:
    raise NotImplementedError("Encrypted data cannot be downgraded in place; restore a backup instead.")
