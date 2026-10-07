"""Browser push subscriptions, for the daily crate reminder.

Revision ID: 0007_push_subscriptions
Revises: 0006_boxes_and_events
Create Date: 2026-10-04

One row per subscribed device, tied to the sign-in session it was made in.
Checks before it acts, like the revisions before it: MariaDB commits DDL as it
goes, so a run that fails part-way has to be resumable on the next boot.
"""
import sqlalchemy as sa
from alembic import op

revision = '0007_push_subscriptions'
down_revision = '0006_boxes_and_events'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade():
    if not _inspector().has_table('push_subscriptions'):
        op.create_table('push_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint_hash', sa.String(length=64), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.String(length=128), nullable=True),
        sa.Column('auth', sa.String(length=64), nullable=True),
        sa.Column('session_id', sa.String(length=64), nullable=True),
        sa.Column('session_expires_at', sa.DateTime(), nullable=True),
        sa.Column('token_version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint_hash', name='uq_push_subscriptions_endpoint_hash')
        )

    indexes = {ix['name'] for ix in _inspector().get_indexes('push_subscriptions')}
    if 'ix_push_subscriptions_user_id' not in indexes:
        op.create_index(op.f('ix_push_subscriptions_user_id'), 'push_subscriptions',
                        ['user_id'], unique=False)
    if 'ix_push_subscriptions_session_id' not in indexes:
        op.create_index(op.f('ix_push_subscriptions_session_id'), 'push_subscriptions',
                        ['session_id'], unique=False)


def downgrade():
    op.drop_table('push_subscriptions')
