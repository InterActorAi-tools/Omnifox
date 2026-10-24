"""private projects for project managers; objectives encrypted

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24

- projects get an owner and an is_private flag; project_shares lists the
  users a private project is shared with.
- Objectives are encrypted at rest like other user data.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from utils.crypto import encrypt

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_projects_owner_id_users", "users", ["owner_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_projects_owner_id", ["owner_id"])
        batch.alter_column("objectives", type_=sa.Text(), server_default=None, postgresql_using="objectives::text")

    op.create_table(
        "project_shares",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    bind = op.get_bind()
    for project_id, objectives in bind.execute(sa.text("SELECT id, objectives FROM projects")).fetchall():
        bind.execute(sa.text("UPDATE projects SET objectives = :value WHERE id = :id"),
                     {"value": encrypt(str(objectives or "[]").encode()).decode(), "id": project_id})


def downgrade() -> None:
    raise NotImplementedError("Encrypted data cannot be downgraded in place; restore a backup instead.")
