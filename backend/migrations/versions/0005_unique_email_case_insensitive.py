"""one account per email, ignoring case

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13

Basic@x.com and basic@x.com could be registered as two accounts. The app
now looks emails up case-insensitively; this index enforces it. If an
existing database already holds such duplicates, the index is skipped
(and the duplicates logged) instead of failing the deploy: merge or
delete them, then run `alembic upgrade head` again after `alembic
downgrade 0004`.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(
        "SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1")).fetchall()
    if duplicates:
        logging.getLogger("alembic").warning(
            "users: %d email(s) exist in more than one letter case; unique index skipped", len(duplicates))
        return
    op.create_index("ux_users_email_lower", "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_users_email_lower")
