"""Alert channels: every place a staff alert can go.

Revision ID: 0002_alert_channels
Revises: 0001_baseline
Create Date: 2026-08-22

One table for all three kinds of destination - a Discord webhook, the staff
inbox, an ops mailbox - because everything except the sending is identical
between them: same event catalog, same server filter, same failure handling. A
fourth kind should be a row, not a schema change.

The staff inbox is seeded here, subscribed to the two events that produced staff
notifications before any of this existed - operational alerts and new reports.
Those call sites now go through the channel system, so without the seed an
install would come up quieter than the version before it, which is not a change
anybody asked for.
"""
import sqlalchemy as sa
from alembic import op

revision = '0002_alert_channels'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alert_channels',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('events', sa.JSON(), nullable=False),
    sa.Column('server_ids', sa.JSON(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=16), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('failure_count', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    op.execute("""
        INSERT INTO alert_channels
            (kind, name, target, events, server_ids, enabled, created_at,
             updated_at, failure_count)
        VALUES
            ('inapp', 'Staff inbox', NULL,
             '["alert.raised", "report.created"]', NULL, true,
             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
    """)


def downgrade():
    op.drop_table('alert_channels')
