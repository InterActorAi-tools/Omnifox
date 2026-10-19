"""baseline schema (tables as created by create_all before Alembic)

Revision ID: 0001
Revises: 
Create Date: 2026-10-12 14:11:41.365506
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: databases created before Alembic (Base.metadata.create_all)
    # already have some or all of these tables. Create only what is missing.
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'invitations' not in existing:
        op.create_table('invitations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_invitations_id'), 'invitations', ['id'], unique=False)
        op.create_index(op.f('ix_invitations_token'), 'invitations', ['token'], unique=True)

    if 'permissions' not in existing:
        op.create_table('permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )
        op.create_index(op.f('ix_permissions_id'), 'permissions', ['id'], unique=False)

    if 'projects' not in existing:
        op.create_table('projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_projects_id'), 'projects', ['id'], unique=False)
        op.create_index(op.f('ix_projects_name'), 'projects', ['name'], unique=True)

    if 'roles' not in existing:
        op.create_table('roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
        )
        op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False)

    if 'tasks' not in existing:
        op.create_table('tasks',
        sa.Column('task_id', sa.String(length=255), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('task_type', sa.String(length=64), nullable=False),
        sa.Column('metadata_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('result_data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('task_id')
        )
        op.create_index('ix_tasks_client_id_created_at', 'tasks', ['client_id', sa.literal_column('created_at DESC')], unique=False)

    if 'url_cache' not in existing:
        op.create_table('url_cache',
        sa.Column('url_hash', sa.String(length=64), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('project', sa.String(length=255), nullable=False),
        sa.Column('extracted_filename', sa.String(length=255), nullable=False),
        sa.Column('processed_filename', sa.String(length=255), nullable=True),
        sa.Column('comments_count', sa.Integer(), nullable=False),
        sa.Column('sentiment_data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('is_processed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('last_accessed', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('url_hash')
        )
        op.create_index(op.f('ix_url_cache_created_at'), 'url_cache', ['created_at'], unique=False)

    if 'usage_records' not in existing:
        op.create_table('usage_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.Float(), nullable=False),
        sa.Column('project', sa.String(length=255), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('comments_count', sa.Integer(), nullable=False),
        sa.Column('operation_type', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_usage_records_id'), 'usage_records', ['id'], unique=False)
        op.create_index('ix_usage_records_project', 'usage_records', ['project'], unique=False)
        op.create_index('ix_usage_records_timestamp', 'usage_records', ['timestamp'], unique=False)

    if 'users' not in existing:
        op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=True),
        sa.Column('google_id', sa.String(length=255), nullable=True),
        sa.Column('auth_provider', sa.String(length=20), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('picture_url', sa.Text(), nullable=True),
        sa.Column('email_verified', sa.Boolean(), nullable=True),
        sa.Column('verification_token', sa.String(length=255), nullable=True),
        sa.Column('verification_token_expires', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reset_token_hash', sa.String(length=255), nullable=True),
        sa.Column('reset_token_expires', sa.DateTime(timezone=True), nullable=True),
        sa.Column('two_factor_secret', sa.String(length=32), nullable=True),
        sa.Column('two_factor_enabled', sa.Boolean(), nullable=True),
        sa.Column('backup_codes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=True),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('verification_token')
        )
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
        op.create_index(op.f('ix_users_google_id'), 'users', ['google_id'], unique=True)
        op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
        op.create_index(op.f('ix_users_reset_token_hash'), 'users', ['reset_token_hash'], unique=True)

    if 'activity_logs' not in existing:
        op.create_table('activity_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('extra_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_activity_logs_action'), 'activity_logs', ['action'], unique=False)
        op.create_index(op.f('ix_activity_logs_created_at'), 'activity_logs', ['created_at'], unique=False)
        op.create_index(op.f('ix_activity_logs_id'), 'activity_logs', ['id'], unique=False)

    if 'refresh_tokens' not in existing:
        op.create_table('refresh_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('device_name', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('is_revoked', sa.Boolean(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('last_used', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_refresh_tokens_id'), 'refresh_tokens', ['id'], unique=False)
        op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)

    if 'role_permissions' not in existing:
        op.create_table('role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
        )

    if 'user_roles' not in existing:
        op.create_table('user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
        )

def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_activity_logs_id'), table_name='activity_logs')
    op.drop_index(op.f('ix_activity_logs_created_at'), table_name='activity_logs')
    op.drop_index(op.f('ix_activity_logs_action'), table_name='activity_logs')
    op.drop_table('activity_logs')
    op.drop_index(op.f('ix_users_reset_token_hash'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_index(op.f('ix_users_google_id'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index('ix_usage_records_timestamp', table_name='usage_records')
    op.drop_index('ix_usage_records_project', table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_id'), table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_url_cache_created_at'), table_name='url_cache')
    op.drop_table('url_cache')
    op.drop_index('ix_tasks_client_id_created_at', table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_roles_id'), table_name='roles')
    op.drop_table('roles')
    op.drop_index(op.f('ix_projects_name'), table_name='projects')
    op.drop_index(op.f('ix_projects_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_permissions_id'), table_name='permissions')
    op.drop_table('permissions')
    op.drop_index(op.f('ix_invitations_token'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_id'), table_name='invitations')
    op.drop_table('invitations')
    # ### end Alembic commands ###
