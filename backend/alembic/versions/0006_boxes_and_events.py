"""Named boxes and events, in place of fixed box sizes.

Revision ID: 0006_boxes_and_events
Revises: 0005_staff_feed
Create Date: 2026-09-29

A box used to be one of four fixed sizes (`box_types`, keyed by `size`), and the
daily roll picked a size by the weight stored on the type. Now a box is a named
record (`boxes`) with its own loot pool, and an *event* (`events`) decides which
box a player receives by a weighted pick from its line-up (`event_boxes`). The
daily grant and the weekly streak bonus become the two system events; custom
events stack on top.

Existing data is carried over rather than dropped:

- every box type becomes a box of the same draws, named after its label;
- the daily event's line-up is every active type with a positive weight, at
  that weight, and the weekly bonus event's line-up is the `bonus` type - which
  is exactly what the old roll and the old streak job did;
- loot pool entries point at the new box, and take the quantity that used to
  live on the reward (`rewards.count`), which now lives on the pool entry so
  the same item can drop in different amounts from different boxes;
- inventory items keep the quantity they would have delivered;
- granted boxes are keyed `(user_id, event_id, period_key)` with the period
  being the grant date - the calendar day for a daily box, the week-ending day
  for a bonus - so nothing already granted can be claimed a second time;
- the `streak_bonus_enabled` setting becomes the weekly bonus event's
  `enabled` flag, which is where that switch now lives.

Because this seeds the system events, init_db's first-boot seed sees them and
does nothing, on an upgraded database and on a fresh one alike.

Safe to re-run after a failure: MariaDB cannot roll DDL back, so every step
checks the schema before acting and skips what an earlier attempt already did
(see `upgrade`).

Not reversible: once custom events or more boxes exist there is no fixed size
to map them back to.
"""
import os
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = '0006_boxes_and_events'
down_revision = '0005_staff_feed'
branch_labels = None
depends_on = None


BONUS_SIZE = 'bonus'

box_types = sa.table(
    'box_types',
    sa.column('size', sa.String),
    sa.column('label', sa.String),
    sa.column('draws', sa.Integer),
    sa.column('weight', sa.Float),
    sa.column('active', sa.Boolean),
)
boxes = sa.table(
    'boxes',
    sa.column('id', sa.Integer),
    sa.column('name', sa.String),
    sa.column('draws', sa.Integer),
    sa.column('created_at', sa.DateTime),
    sa.column('updated_at', sa.DateTime),
)
events = sa.table(
    'events',
    sa.column('id', sa.Integer),
    sa.column('type', sa.String),
    sa.column('name', sa.String),
    sa.column('description', sa.Text),
    sa.column('enabled', sa.Boolean),
    sa.column('cadence', sa.String),
    sa.column('system', sa.Boolean),
    sa.column('created_at', sa.DateTime),
    sa.column('updated_at', sa.DateTime),
)
event_boxes = sa.table(
    'event_boxes',
    sa.column('event_id', sa.Integer),
    sa.column('box_id', sa.Integer),
    sa.column('weight', sa.Float),
)
rewards = sa.table(
    'rewards',
    sa.column('id', sa.Integer),
    sa.column('count', sa.Integer),
)
box_loot_pools = sa.table(
    'box_loot_pools',
    sa.column('id', sa.Integer),
    sa.column('size', sa.String),
    sa.column('box_id', sa.Integer),
    sa.column('reward_id', sa.Integer),
    sa.column('count', sa.Integer),
)
inventory_items = sa.table(
    'inventory_items',
    sa.column('reward_id', sa.Integer),
    sa.column('count', sa.Integer),
)
user_boxes = sa.table(
    'user_boxes',
    sa.column('id', sa.Integer),
    sa.column('size', sa.String),
    sa.column('source', sa.String),
    sa.column('grant_date', sa.Date),
    sa.column('box_id', sa.Integer),
    sa.column('event_id', sa.Integer),
    sa.column('period_key', sa.String),
)
app_settings = sa.table(
    'app_settings',
    sa.column('key', sa.String),
    sa.column('value', sa.Text),
)


def _as_bool(raw):
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _period_key(grant_date):
    # MariaDB hands back a date; SQLite may hand back its stored text.
    if hasattr(grant_date, 'isoformat'):
        return grant_date.isoformat()
    return str(grant_date)[:10]


# -- Schema probes. A fresh inspector every time: the cached one would not see
# what the previous step just changed.

def _insp():
    return sa.inspect(op.get_bind())


def _has_table(table):
    return _insp().has_table(table)


def _columns(table):
    return {c['name']: c for c in _insp().get_columns(table)}


def _indexes(table):
    return {ix['name']: ix['column_names'] for ix in _insp().get_indexes(table)}


def _uniques(table):
    """Unique constraints by name -> columns. MariaDB reports them as unique
    indexes, SQLite as constraints, so both are merged."""
    insp = _insp()
    found = {uc['name']: uc['column_names'] for uc in insp.get_unique_constraints(table)}
    found.update({ix['name']: ix['column_names']
                  for ix in insp.get_indexes(table) if ix.get('unique')})
    return found


def _has_fk(table, column):
    return any(fk['constrained_columns'] == [column]
               for fk in _insp().get_foreign_keys(table))


def _add_column(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column(table, name):
    if name in _columns(table):
        op.drop_column(table, name)


def _create_index(table, name, columns):
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def _drop_index(table, name):
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def _replace_unique(table, name, new_columns):
    """Point the named unique constraint at `new_columns`, whatever it covers now."""
    current = _uniques(table).get(name)
    if current is not None and list(current) != list(new_columns):
        op.drop_constraint(name, table, type_='unique')
        current = None
    if current is None:
        op.create_unique_constraint(name, table, new_columns)


def _make_not_null(table, name, type_):
    if _columns(table)[name]['nullable']:
        op.alter_column(table, name, existing_type=type_, nullable=False)


def _create_fk(name, table, column, target, ondelete=None):
    if not _has_fk(table, column):
        op.create_foreign_key(name, table, target, [column], ['id'], ondelete=ondelete)


def _ensure_new_tables():
    if not _has_table('boxes'):
        op.create_table('boxes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('draws', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_boxes_name')
        )
    if not _has_table('events'):
        op.create_table('events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('cadence', sa.String(length=16), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('system', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    _create_index('events', 'ix_events_type', ['type'])
    if not _has_table('event_boxes'):
        op.create_table('event_boxes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('box_id', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['box_id'], ['boxes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'box_id', name='uq_event_box')
        )
    _create_index('event_boxes', 'ix_event_boxes_event_id', ['event_id'])
    _create_index('event_boxes', 'ix_event_boxes_box_id', ['box_id'])


def _map_sizes_to_boxes(conn, types, now):
    """One box per legacy size, reusing a box an earlier attempt already made.

    Names are derived deterministically (sorted sizes, label else title-cased
    size), so a re-run arrives at the same names and finds its own rows.
    """
    sizes = set(types)
    if 'size' in _columns('box_loot_pools'):
        sizes |= {s for (s,) in conn.execute(sa.select(box_loot_pools.c.size).distinct())}
    if 'size' in _columns('user_boxes'):
        sizes |= {s for (s,) in conn.execute(sa.select(user_boxes.c.size).distinct())}

    box_ids = {}
    used_names = set()
    for size in sorted(sizes):
        row = types.get(size)
        name = ((row.label if row is not None else None) or size.title())[:64]
        if name.lower() in used_names:
            name = f'{name} ({size})'[:64]
        used_names.add(name.lower())

        existing = conn.execute(sa.select(boxes.c.id).where(boxes.c.name == name)).scalar()
        if existing is None:
            conn.execute(boxes.insert().values(
                name=name, draws=(row.draws if row is not None else 1),
                created_at=now, updated_at=now))
            existing = conn.execute(
                sa.select(boxes.c.id).where(boxes.c.name == name)).scalar_one()
        box_ids[size] = existing
    return box_ids


def _system_event(conn, event_type):
    return conn.execute(sa.select(events.c.id).where(
        events.c.type == event_type, events.c.system.is_(True))).scalar()


def _ensure_system_events(conn, now):
    """The daily and weekly bonus events, created once. The weekly bonus's
    on/off switch used to be the `streak_bonus_enabled` setting (an override
    row, else the environment default)."""
    if _system_event(conn, 'daily') is None:
        conn.execute(events.insert().values(
            type='daily', name='Daily box', system=True, enabled=True, cadence='daily',
            description='One box every day, picked by weight from the boxes below.',
            created_at=now, updated_at=now))

    if _system_event(conn, 'weekly_bonus') is None:
        override = conn.execute(
            sa.select(app_settings.c.value)
            .where(app_settings.c.key == 'streak_bonus_enabled')
        ).scalar()
        enabled = _as_bool(override if override is not None
                           else os.getenv('STREAK_BONUS_ENABLED', 'true'))
        conn.execute(events.insert().values(
            type='weekly_bonus', name='Weekly bonus', system=True,
            enabled=enabled, cadence='weekly',
            description='A bonus box for players who collected enough daily '
                        'boxes during the week.',
            created_at=now, updated_at=now))

    conn.execute(app_settings.delete().where(app_settings.c.key == 'streak_bonus_enabled'))
    return _system_event(conn, 'daily'), _system_event(conn, 'weekly_bonus')


def _ensure_line_ups(conn, types, box_ids, daily_id, weekly_id):
    wanted = []
    for size, row in types.items():
        if size == BONUS_SIZE:
            wanted.append((weekly_id, box_ids[size], 1.0))
        elif row.active and (row.weight or 0) > 0:
            wanted.append((daily_id, box_ids[size], row.weight))
    for event_id, box_id, weight in wanted:
        present = conn.execute(sa.select(event_boxes.c.event_id).where(
            event_boxes.c.event_id == event_id, event_boxes.c.box_id == box_id)).first()
        if present is None:
            conn.execute(event_boxes.insert().values(
                event_id=event_id, box_id=box_id, weight=weight))


def _copy_reward_count(conn, table):
    """Fill `table.count` from the reward, while the reward still carries it."""
    if 'count' not in _columns('rewards'):
        return
    reward_count = (sa.select(rewards.c.count)
                    .where(rewards.c.id == table.c.reward_id)
                    .scalar_subquery())
    conn.execute(table.update().values(count=sa.func.coalesce(reward_count, 1)))


def upgrade():
    """Every step checks before it acts.

    MariaDB commits DDL as it goes, so a run that fails part-way leaves its
    earlier steps applied with the revision unrecorded, and the next boot runs
    this again from the top. Each step therefore looks at the schema first and
    only does what is still missing - which also lets a database built from a
    pre-release baseline that already had the new shape pass straight through.

    Order matters for the data: the quantity is copied off `rewards` before its
    column is dropped, and `box_types` - the source of the size mapping - is
    dropped last, so an interrupted run can always rebuild the mapping.
    """
    conn = op.get_bind()
    now = datetime.utcnow()

    _ensure_new_tables()

    legacy = (_has_table('box_types')
              or 'size' in _columns('box_loot_pools')
              or 'size' in _columns('user_boxes'))

    box_ids = {}
    daily_id = weekly_id = None
    if legacy:
        types = ({row.size: row for row in conn.execute(sa.select(box_types))}
                 if _has_table('box_types') else {})
        box_ids = _map_sizes_to_boxes(conn, types, now)
        daily_id, weekly_id = _ensure_system_events(conn, now)
        _ensure_line_ups(conn, types, box_ids, daily_id, weekly_id)
    # Otherwise the database never had sizes, and init_db seeds the starter
    # boxes and events on boot as it does for any new database.

    # -- Loot pools: size -> box_id, and the quantity moves here from the reward.
    _add_column('box_loot_pools', sa.Column('box_id', sa.Integer(), nullable=True))
    _add_column('box_loot_pools', sa.Column('count', sa.Integer(), nullable=False,
                                            server_default='1'))
    if 'size' in _columns('box_loot_pools'):
        for size, box_id in box_ids.items():
            conn.execute(box_loot_pools.update()
                         .where(box_loot_pools.c.size == size,
                                box_loot_pools.c.box_id.is_(None))
                         .values(box_id=box_id))
    _copy_reward_count(conn, box_loot_pools)

    _replace_unique('box_loot_pools', 'uq_box_pool', ['box_id', 'reward_id'])
    _drop_index('box_loot_pools', 'ix_box_loot_pools_size')
    _drop_column('box_loot_pools', 'size')
    _make_not_null('box_loot_pools', 'box_id', sa.Integer())
    op.alter_column('box_loot_pools', 'count', existing_type=sa.Integer(),
                    existing_nullable=False, server_default=None)
    _create_index('box_loot_pools', 'ix_box_loot_pools_box_id', ['box_id'])
    _create_fk('fk_box_loot_pools_box_id', 'box_loot_pools', 'box_id', 'boxes',
               ondelete='CASCADE')

    # -- Inventory items keep the quantity they would have delivered.
    _add_column('inventory_items', sa.Column('count', sa.Integer(), nullable=False,
                                             server_default='1'))
    _copy_reward_count(conn, inventory_items)
    op.alter_column('inventory_items', 'count', existing_type=sa.Integer(),
                    existing_nullable=False, server_default=None)

    # Only now that both copies are made.
    _drop_column('rewards', 'count')

    # -- Granted boxes: size -> box, source -> event, grant date -> period.
    _add_column('user_boxes', sa.Column('box_id', sa.Integer(), nullable=True))
    _add_column('user_boxes', sa.Column('event_id', sa.Integer(), nullable=True))
    _add_column('user_boxes', sa.Column('period_key', sa.String(length=32), nullable=True))

    if 'size' in _columns('user_boxes'):
        rows = conn.execute(
            sa.select(user_boxes.c.id, user_boxes.c.size,
                      user_boxes.c.source, user_boxes.c.grant_date)
            .where(user_boxes.c.box_id.is_(None))).all()
        if rows:
            conn.execute(
                user_boxes.update()
                .where(user_boxes.c.id == sa.bindparam('_id'))
                .values(box_id=sa.bindparam('_box_id'),
                        event_id=sa.bindparam('_event_id'),
                        period_key=sa.bindparam('_period_key')),
                [{'_id': r.id,
                  '_box_id': box_ids[r.size],
                  '_event_id': weekly_id if r.source == 'bonus' else daily_id,
                  '_period_key': _period_key(r.grant_date)}
                 for r in rows])

    _replace_unique('user_boxes', 'uq_user_box_grant', ['user_id', 'event_id', 'period_key'])
    _drop_column('user_boxes', 'size')
    _make_not_null('user_boxes', 'box_id', sa.Integer())
    _make_not_null('user_boxes', 'period_key', sa.String(length=32))
    _create_index('user_boxes', 'ix_user_boxes_box_id', ['box_id'])
    _create_index('user_boxes', 'ix_user_boxes_event_id', ['event_id'])
    _create_fk('fk_user_boxes_box_id', 'user_boxes', 'box_id', 'boxes')
    _create_fk('fk_user_boxes_event_id', 'user_boxes', 'event_id', 'events',
               ondelete='SET NULL')

    if _has_table('box_types'):
        op.drop_table('box_types')


def downgrade():
    raise NotImplementedError(
        '0006_boxes_and_events cannot be reversed: named boxes and custom events '
        'have no fixed box size to map back to. Restore a backup instead.')
