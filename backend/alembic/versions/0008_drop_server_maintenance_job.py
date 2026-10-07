"""Drop the `server_maintenance` scheduled job.

Revision ID: 0008_drop_server_maintenance_job
Revises: 0007_push_subscriptions
Create Date: 2026-10-05

The job queued an update task after a single broadcast and stopped nothing, so
it could replace the game files under a running server. Maintenance is now the
game-server's own worker (checks, a planned run, a countdown, and a hold on
every server while the files change), configured from Installations.

The row has to go with the handler: the scheduler runs any enabled row it finds
and would otherwise report "no handler registered" on every interval.
"""
import sqlalchemy as sa
from alembic import op

revision = '0008_drop_server_maintenance_job'
down_revision = '0007_push_subscriptions'
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table('scheduled_jobs'):
        op.execute("DELETE FROM scheduled_jobs WHERE kind = 'server_maintenance'")


def downgrade():
    # The scheduler re-registers any kind the code still knows, disabled; the
    # code no longer knows this one, so there is nothing to put back.
    pass
