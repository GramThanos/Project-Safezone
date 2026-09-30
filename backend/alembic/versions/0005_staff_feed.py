"""Staff feed: one row per alert, and how far each staff member has read it.

Revision ID: 0005_staff_feed
Revises: 0004_reward_commands
Create Date: 2026-09-29

The in-app alert destination used to write a `notifications` row per moderator.
It now writes a single `staff_alerts` row that every moderator and admin reads,
and the only genuinely per-person part - how far each of them has got - is
`users.staff_alerts_read_at`. Null reads as "never opened it", so every existing
account starts with the whole feed unread, which is empty anyway on upgrade.

Existing staff notifications are left where they are: they were delivered as
notifications and stay readable as such.

Every step checks before it acts. MariaDB commits DDL as it goes, so a run that
fails part-way leaves its earlier steps applied with the revision unrecorded;
the next boot has to be able to pick up from there. A database built from a
pre-release baseline that already had these objects passes straight through.
"""
import sqlalchemy as sa
from alembic import op

revision = '0005_staff_feed'
down_revision = '0004_reward_commands'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade():
    insp = _inspector()
    if not insp.has_table('staff_alerts'):
        op.create_table('staff_alerts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=140), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('link', sa.String(length=255), nullable=True),
        sa.Column('server_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )

    indexes = {ix['name'] for ix in _inspector().get_indexes('staff_alerts')}
    if 'ix_staff_alerts_event' not in indexes:
        op.create_index(op.f('ix_staff_alerts_event'), 'staff_alerts', ['event'], unique=False)
    if 'ix_staff_alerts_created_at' not in indexes:
        op.create_index('ix_staff_alerts_created_at', 'staff_alerts', ['created_at'], unique=False)

    if 'staff_alerts_read_at' not in {c['name'] for c in _inspector().get_columns('users')}:
        op.add_column('users', sa.Column('staff_alerts_read_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('users', 'staff_alerts_read_at')
    op.drop_table('staff_alerts')
