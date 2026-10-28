"""settlement link, account iban, category rule sign

Revision ID: 8a56f61e98ab
Revises: c572d7080be2
Create Date: 2026-09-28 17:25:12.650819

* transactions.settles_statement_id — explicit link from a bank payment to
  the credit-card statement it settles. Previously this was only implied
  by "is_transfer=True and transfer_pair_id IS NULL", which could not be
  told apart from a manually marked transfer. Backfilled from the
  existing reconciliations.
* accounts.iban — optional, used by transfer detection.
* category_rules.amount_sign — lets a rule apply only to money in or out
  (e.g. "Salary" never matches a tax payment containing "Lohn").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8a56f61e98ab'
down_revision: Union[str, Sequence[str], None] = 'c572d7080be2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('iban', sqlmodel.sql.sqltypes.AutoString(length=34), nullable=True))

    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('amount_sign', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='any')
        )

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('settles_statement_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_transactions_settles_statement_id'), ['settles_statement_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_transactions_settles_statement_id', 'credit_card_statements', ['settles_statement_id'], ['id']
        )

    op.execute(
        "UPDATE transactions SET settles_statement_id = ("
        "  SELECT r.statement_id FROM reconciliations r WHERE r.bank_debit_transaction_id = transactions.id"
        ") WHERE id IN (SELECT bank_debit_transaction_id FROM reconciliations WHERE bank_debit_transaction_id IS NOT NULL)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_transactions_settles_statement_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_transactions_settles_statement_id'))
        batch_op.drop_column('settles_statement_id')

    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.drop_column('amount_sign')

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('iban')
