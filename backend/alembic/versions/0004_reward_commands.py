"""Free-text command sequences for usable rewards.

Revision ID: 0004_reward_commands
Revises: 0003_totp
Create Date: 2026-08-23

A usable reward used to be a single catalog action (`action_id` + `action_params`).
It now carries a free-text `commands` block instead: one or more console commands
(optionally interleaved with executor-side `sleep`/`wait` steps), with a
`{{USERNAME}}` placeholder for the recipient. `commands` is nullable because item
rewards never set it, and because the two legacy columns are left in place so any
reward authored before this upgrade still reads back - the delivery path accepts
either shape.
"""
import sqlalchemy as sa
from alembic import op

revision = '0004_reward_commands'
down_revision = '0003_totp'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rewards', sa.Column('commands', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('rewards', 'commands')
