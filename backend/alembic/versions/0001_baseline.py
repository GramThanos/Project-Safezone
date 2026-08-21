"""Baseline: the backend's schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-20

Every table the backend owns, spelled out. `servers`, `tasks` and
`server_player_counts` are absent on purpose - the game-server owns those and
migrates them itself, and `alembic/env.py` filters them out so autogenerate
never proposes dropping a table it simply does not know about.

**Do not call `Base.metadata.create_all()` from a migration.** The first version
of this file did, and it built whatever the models described at the moment it
ran - which meant it created the tables that later revisions were written to
add, and every one of them failed with "table already exists". A migration has
to be frozen in time; the models are not.
"""
import sqlalchemy as sa
from alembic import op

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('target', sa.String(length=128), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_user_id'), 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_table('box_types',
    sa.Column('size', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=48), nullable=True),
    sa.Column('draws', sa.Integer(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('size')
    )
    op.create_table('rewards',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('icon', sa.String(length=512), nullable=True),
    sa.Column('in_game_id', sa.String(length=64), nullable=True),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('action_id', sa.String(length=64), nullable=True),
    sa.Column('action_params', sa.JSON(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rewards_kind'), 'rewards', ['kind'], unique=False)
    op.create_table('scheduled_jobs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('interval_seconds', sa.Integer(), nullable=False),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_result', sa.Text(), nullable=True),
    sa.Column('running_since', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_jobs_kind'), 'scheduled_jobs', ['kind'], unique=True)
    op.create_index(op.f('ix_scheduled_jobs_next_run_at'), 'scheduled_jobs', ['next_run_at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('invited_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('auth_tokens',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.String(length=16), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_auth_tokens_purpose'), 'auth_tokens', ['purpose'], unique=False)
    op.create_index(op.f('ix_auth_tokens_token_hash'), 'auth_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_auth_tokens_user_id'), 'auth_tokens', ['user_id'], unique=False)
    op.create_table('bans',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('issued_by', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('prior_role', sa.String(length=20), nullable=True),
    sa.Column('lifted_at', sa.DateTime(), nullable=True),
    sa.Column('lifted_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bans_expires_at'), 'bans', ['expires_at'], unique=False)
    op.create_index(op.f('ix_bans_user_id'), 'bans', ['user_id'], unique=False)
    op.create_table('box_loot_pools',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('size', sa.String(length=16), nullable=False),
    sa.Column('reward_id', sa.Integer(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['reward_id'], ['rewards.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('size', 'reward_id', name='uq_box_pool')
    )
    op.create_index(op.f('ix_box_loot_pools_reward_id'), 'box_loot_pools', ['reward_id'], unique=False)
    op.create_index(op.f('ix_box_loot_pools_size'), 'box_loot_pools', ['size'], unique=False)
    op.create_table('characters',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('avatar', sa.String(length=255), nullable=True),
    sa.Column('stats', sa.Text(), nullable=True),
    sa.Column('server_id', sa.Integer(), nullable=True),
    sa.Column('in_game_username', sa.String(length=32), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_characters_in_game_username'), 'characters', ['in_game_username'], unique=False)
    op.create_index(op.f('ix_characters_last_seen_at'), 'characters', ['last_seen_at'], unique=False)
    op.create_index(op.f('ix_characters_name'), 'characters', ['name'], unique=False)
    op.create_index(op.f('ix_characters_server_id'), 'characters', ['server_id'], unique=False)
    op.create_index(op.f('ix_characters_user_id'), 'characters', ['user_id'], unique=False)
    op.create_table('claim_requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('in_game_username', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('character_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_claim_requests_in_game_username'), 'claim_requests', ['in_game_username'], unique=False)
    op.create_index(op.f('ix_claim_requests_server_id'), 'claim_requests', ['server_id'], unique=False)
    op.create_index(op.f('ix_claim_requests_status'), 'claim_requests', ['status'], unique=False)
    op.create_index(op.f('ix_claim_requests_user_id'), 'claim_requests', ['user_id'], unique=False)
    op.create_table('inventory_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reward_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('source_box_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('character_id', sa.Integer(), nullable=True),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('delivered_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['reward_id'], ['rewards.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inventory_items_reward_id'), 'inventory_items', ['reward_id'], unique=False)
    op.create_index(op.f('ix_inventory_items_status'), 'inventory_items', ['status'], unique=False)
    op.create_index(op.f('ix_inventory_items_user_id'), 'inventory_items', ['user_id'], unique=False)
    op.create_table('invitations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('max_uses', sa.Integer(), nullable=False),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invitations_code_hash'), 'invitations', ['code_hash'], unique=True)
    op.create_index(op.f('ix_invitations_created_by'), 'invitations', ['created_by'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=140), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('link', sa.String(length=255), nullable=True),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index('ix_notifications_user_read', 'notifications', ['user_id', 'read_at', 'created_at'], unique=False)
    op.create_table('reports',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('reporter_user_id', sa.Integer(), nullable=False),
    sa.Column('subject_username', sa.String(length=64), nullable=True),
    sa.Column('server_id', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_kind'), 'reports', ['kind'], unique=False)
    op.create_index(op.f('ix_reports_reporter_user_id'), 'reports', ['reporter_user_id'], unique=False)
    op.create_index(op.f('ix_reports_status'), 'reports', ['status'], unique=False)
    op.create_index('ix_reports_status_created', 'reports', ['status', 'created_at'], unique=False)
    op.create_table('user_boxes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('size', sa.String(length=16), nullable=False),
    sa.Column('grant_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('granted_at', sa.DateTime(), nullable=False),
    sa.Column('opened_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'grant_date', 'source', name='uq_user_box_grant')
    )
    op.create_index(op.f('ix_user_boxes_user_id'), 'user_boxes', ['user_id'], unique=False)

    # Seeded here, not left to first boot: a deployment that only runs
    # migrations still needs a working economy. `bonus` carries weight 0 so it
    # is never rolled on login - only the weekly streak job grants it.
    op.bulk_insert(
        sa.table(
            'box_types',
            sa.column('size', sa.String),
            sa.column('label', sa.String),
            sa.column('draws', sa.Integer),
            sa.column('weight', sa.Float),
            sa.column('active', sa.Boolean),
        ),
        [
            {'size': 'small', 'label': 'Small', 'draws': 1, 'weight': 0.6, 'active': True},
            {'size': 'medium', 'label': 'Medium', 'draws': 2, 'weight': 0.3, 'active': True},
            {'size': 'big', 'label': 'Big', 'draws': 3, 'weight': 0.1, 'active': True},
            {'size': 'bonus', 'label': 'Weekly bonus', 'draws': 4, 'weight': 0.0, 'active': True},
        ],
    )


def downgrade():
    op.drop_table('user_boxes')
    op.drop_table('reports')
    op.drop_table('notifications')
    op.drop_table('invitations')
    op.drop_table('inventory_items')
    op.drop_table('claim_requests')
    op.drop_table('characters')
    op.drop_table('box_loot_pools')
    op.drop_table('bans')
    op.drop_table('auth_tokens')
    op.drop_table('users')
    op.drop_table('scheduled_jobs')
    op.drop_table('rewards')
    op.drop_table('box_types')
    op.drop_table('audit_logs')
    op.drop_table('app_settings')
