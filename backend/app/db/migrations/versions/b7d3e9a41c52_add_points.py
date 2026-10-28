"""add bonus points

Revision ID: b7d3e9a41c52
Revises: 9c2e7d4b1f30
Create Date: 2026-10-24 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d3e9a41c52'
down_revision: Union[str, Sequence[str], None] = '9c2e7d4b1f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'points_programs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column('unit', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('value_per_100', sa.Integer(), nullable=False),
        sa.Column('value_set_by_user', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_table(
        'points_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('program_id', sa.Integer(), nullable=False),
        sa.Column('import_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=12), nullable=False),
        sa.Column('value_minor', sa.Integer(), nullable=True),
        sa.Column('note', sqlmodel.sql.sqltypes.AutoString(length=80), nullable=True),
        sa.ForeignKeyConstraint(['import_id'], ['imports.id']),
        sa.ForeignKeyConstraint(['program_id'], ['points_programs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('points_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_points_entries_entry_date'), ['entry_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_points_entries_import_id'), ['import_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_points_entries_program_id'), ['program_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_points_entries_transaction_id'), ['transaction_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('points_entries')
    op.drop_table('points_programs')
