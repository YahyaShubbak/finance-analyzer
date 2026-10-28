"""add transaction location

Revision ID: 5be3c1f0a7d2
Revises: d41b7c9e2a65
Create Date: 2026-10-22 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '5be3c1f0a7d2'
down_revision: Union[str, Sequence[str], None] = 'd41b7c9e2a65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('country', sqlmodel.sql.sqltypes.AutoString(length=2), nullable=True))
        batch_op.add_column(sa.Column('city', sqlmodel.sql.sqltypes.AutoString(length=80), nullable=True))
        batch_op.add_column(sa.Column('online', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('location_version', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_index(batch_op.f('ix_transactions_country'), ['country'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_transactions_country'))
        batch_op.drop_column('location_version')
        batch_op.drop_column('online')
        batch_op.drop_column('city')
        batch_op.drop_column('country')
