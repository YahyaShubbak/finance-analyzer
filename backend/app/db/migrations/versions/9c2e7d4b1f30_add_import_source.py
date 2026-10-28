"""add import source signature

Revision ID: 9c2e7d4b1f30
Revises: 5be3c1f0a7d2
Create Date: 2026-10-22 23:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9c2e7d4b1f30'
down_revision: Union[str, Sequence[str], None] = '5be3c1f0a7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_key', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True))
        batch_op.add_column(sa.Column('source_info_json', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_imports_source_key'), ['source_key'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_imports_source_key'))
        batch_op.drop_column('source_info_json')
        batch_op.drop_column('source_key')
