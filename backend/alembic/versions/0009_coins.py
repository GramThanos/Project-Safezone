"""Coins: a balance per account, a sell value per reward, the shop, and earning by playing.

Revision ID: 0009_coins
Revises: 0008_drop_server_maintenance_job
Create Date: 2026-10-07

Checks before it acts, like the revisions before it: MariaDB commits DDL as it
goes, so a run that fails part-way has to be resumable on the next boot.

The new NOT NULL columns carry a server default, so existing rows read as a
reward worth one coin, an account holding none, and a holding that can be sold.
"""
import sqlalchemy as sa
from alembic import op

revision = '0009_coins'
down_revision = '0008_drop_server_maintenance_job'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table):
    return {c['name'] for c in _inspector().get_columns(table)}


def _add(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def _index(table, name, columns, unique=False):
    if name not in {ix['name'] for ix in _inspector().get_indexes(table)}:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    _add('rewards', sa.Column('coin_value', sa.Integer(), nullable=False, server_default='1'))
    _add('users', sa.Column('coin_balance', sa.Integer(), nullable=False, server_default='0'))
    _add('inventory_items', sa.Column('sellable', sa.Boolean(), nullable=False,
                                      server_default=sa.true()))
    _add('characters', sa.Column('coin_progress', sa.JSON(), nullable=True))
    _add('characters', sa.Column('coin_identity', sa.String(length=128), nullable=True))
    _add('characters', sa.Column('coin_identities', sa.JSON(), nullable=True))
    _add('characters', sa.Column('coin_saved_at', sa.DateTime(), nullable=True))
    _add('characters', sa.Column('coin_checked_at', sa.DateTime(), nullable=True))
    _add('characters', sa.Column('coin_earned', sa.Integer(), nullable=False, server_default='0'))

    if not _inspector().has_table('shop_categories'):
        op.create_table('shop_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )

    if not _inspector().has_table('shop_items'):
        op.create_table('shop_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('reward_id', sa.Integer(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('daily_limit', sa.Integer(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sold', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['reward_id'], ['rewards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    _index('shop_items', 'ix_shop_items_reward_id', ['reward_id'])

    if not _inspector().has_table('shop_item_categories'):
        op.create_table('shop_item_categories',
        sa.Column('shop_item_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['shop_item_id'], ['shop_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['shop_categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('shop_item_id', 'category_id')
        )
    _index('shop_item_categories', 'ix_shop_item_categories_category_id', ['category_id'])

    if not _inspector().has_table('shop_purchases'):
        op.create_table('shop_purchases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('shop_item_id', sa.Integer(), nullable=False),
        sa.Column('reward_id', sa.Integer(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    _index('shop_purchases', 'ix_shop_purchases_user_item_created',
           ['user_id', 'shop_item_id', 'created_at'])

    if not _inspector().has_table('coin_log'):
        op.create_table('coin_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    _index('coin_log', 'ix_coin_log_user_created', ['user_id', 'created_at'])
    _index('coin_log', 'ix_coin_log_created', ['created_at'])


def downgrade():
    op.drop_table('coin_log')
    op.drop_table('shop_purchases')
    op.drop_table('shop_item_categories')
    op.drop_table('shop_items')
    op.drop_table('shop_categories')
    for column in ('coin_earned', 'coin_checked_at', 'coin_saved_at', 'coin_identities',
                   'coin_identity', 'coin_progress'):
        op.drop_column('characters', column)
    op.drop_column('inventory_items', 'sellable')
    op.drop_column('users', 'coin_balance')
    op.drop_column('rewards', 'coin_value')
