"""Two-factor auth: a TOTP secret and its on/off switch on the user.

Revision ID: 0003_totp
Revises: 0002_alert_channels
Create Date: 2026-08-22

Two columns on `users`. `totp_secret` holds the base32 shared secret; it is
nullable because most accounts never enable 2FA, and because setup writes it
before the user confirms - an abandoned setup leaves a secret that is simply
never consulted, since `totp_enabled` gates every check. `totp_enabled` is the
one that sign-in reads: false for every existing row, so the upgrade changes no
account's login until someone turns it on.
"""
import sqlalchemy as sa
from alembic import op

revision = '0003_totp'
down_revision = '0002_alert_channels'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('totp_secret', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))


def downgrade():
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')
