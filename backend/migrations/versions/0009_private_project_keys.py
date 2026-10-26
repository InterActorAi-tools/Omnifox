"""personal and project keys for private projects

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26

Users get a key pair (private half locked by their password and a recovery
code), sessions hold it while logged in, and each private project's key is
stored sealed for every member. Keys are created at each user's next login.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("public_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("private_key_enc", sa.Text(), nullable=True))
        batch.add_column(sa.Column("private_key_recovery", sa.Text(), nullable=True))
        batch.add_column(sa.Column("key_salt", sa.String(64), nullable=True))
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.add_column(sa.Column("data_key", sa.Text(), nullable=True))
    op.create_table(
        "project_keys",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("sealed_key", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_keys")
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.drop_column("data_key")
    with op.batch_alter_table("users") as batch:
        for column in ("key_salt", "private_key_recovery", "private_key_enc", "public_key"):
            batch.drop_column(column)
