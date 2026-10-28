"""add custom categories

Revision ID: d41b7c9e2a65
Revises: 8a56f61e98ab
Create Date: 2026-10-22 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd41b7c9e2a65'
down_revision: Union[str, Sequence[str], None] = '8a56f61e98ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('custom_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('custom_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_custom_categories_name'), ['name'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('custom_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_custom_categories_name'))
    op.drop_table('custom_categories')
