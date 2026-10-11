"""Store shop category names and descriptions as utf8mb4.

Revision ID: 0010_shop_categories_utf8mb4
Revises: 0009_coins
Create Date: 2026-10-11

Admins mark categories with emoji ("🔫 Weapons"), which are four-byte UTF-8.
A table created as latin1 or MySQL's three-byte utf8 refuses them under strict
mode - the save fails with "Incorrect string value". MariaDB only made utf8mb4
the server default in 11.6, so a database first created on an earlier image
holds its tables in whatever that default was.

Nothing refers to a category by its name - listings, the shop page and its links
all use the id - so converting the text columns changes no identifier. Already
utf8mb4 (any fresh database today) or not MariaDB/MySQL (SQLite in tests): a
no-op.
"""
import sqlalchemy as sa
from alembic import op

revision = '0010_shop_categories_utf8mb4'
down_revision = '0009_coins'
branch_labels = None
depends_on = None

TABLE = 'shop_categories'


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'mysql' or not sa.inspect(bind).has_table(TABLE):
        return
    collation = bind.execute(sa.text(
        "SELECT TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
    ), {'table': TABLE}).scalar()
    if collation and collation.startswith('utf8mb4'):
        return
    op.execute(f"ALTER TABLE {TABLE} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")


def downgrade():
    # Converting back could not hold the emoji already stored; utf8mb4 is a
    # superset of what was there before, so leaving it is the safe direction.
    pass
