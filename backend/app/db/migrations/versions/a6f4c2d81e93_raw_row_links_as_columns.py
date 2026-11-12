"""a raw row's links to bookings are columns

Two facts about an imported row were kept inside its JSON of extra columns
(raw_transactions.extra_fields_json) and searched for as text:

* "_duplicate_of": the row was not made a booking because it is this one,
  imported from another file before. Now duplicate_of_transaction_id, a
  foreign key with an index: a reference to a booking that is gone can no
  longer stay behind (transaction ids are given again), and finding the rows
  of a booking no longer reads every row.
* "_kept_by_user": the user imported the row as a booking of its own
  although it looked like one already there. Now kept_by_user.

The values are moved out of the JSON (which keeps the file's own columns). A
"_duplicate_of" naming a booking that no longer exists is dropped.

Revision ID: a6f4c2d81e93
Revises: e3a91f5c7d08
Create Date: 2026-11-12 18:00:00

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6f4c2d81e93'
down_revision: Union[str, Sequence[str], None] = 'e3a91f5c7d08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DUPLICATE_OF = "_duplicate_of"
_KEPT_BY_USER = "_kept_by_user"


def _extra(text) -> dict | None:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('raw_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duplicate_of_transaction_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('kept_by_user', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(
            batch_op.f('ix_raw_transactions_duplicate_of_transaction_id'), ['duplicate_of_transaction_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_raw_transactions_duplicate_of_transaction_id', 'transactions', ['duplicate_of_transaction_id'], ['id']
        )

    connection = op.get_bind()
    bookings = {row[0] for row in connection.execute(sa.text("SELECT id FROM transactions"))}
    rows = connection.execute(sa.text(
        "SELECT id, extra_fields_json FROM raw_transactions "
        "WHERE extra_fields_json LIKE :duplicate_of OR extra_fields_json LIKE :kept_by_user"
    ), {"duplicate_of": f'%"{_DUPLICATE_OF}"%', "kept_by_user": f'%"{_KEPT_BY_USER}"%'}).fetchall()
    for raw_id, text in rows:
        extra = _extra(text)
        if extra is None:
            continue
        # Only what the app wrote itself: a number, and `true`. A file's own
        # column that happens to have one of these names stays where it is.
        target = extra.get(_DUPLICATE_OF)
        is_link = isinstance(target, int) and not isinstance(target, bool)
        kept = extra.get(_KEPT_BY_USER) is True
        if not is_link and not kept:
            continue
        if is_link:
            del extra[_DUPLICATE_OF]
        if kept:
            del extra[_KEPT_BY_USER]
        connection.execute(sa.text(
            "UPDATE raw_transactions SET duplicate_of_transaction_id = :target, kept_by_user = :kept, "
            "extra_fields_json = :extra WHERE id = :id"
        ), {
            "target": target if is_link and target in bookings else None,
            "kept": kept,
            "extra": json.dumps(extra, ensure_ascii=False) if extra else None,
            "id": raw_id,
        })


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT id, extra_fields_json, duplicate_of_transaction_id, kept_by_user FROM raw_transactions "
        "WHERE duplicate_of_transaction_id IS NOT NULL OR kept_by_user"
    )).fetchall()
    for raw_id, text, target, kept in rows:
        extra = _extra(text)
        if extra is None:
            continue
        if target is not None:
            extra[_DUPLICATE_OF] = target
        if kept:
            extra[_KEPT_BY_USER] = True
        connection.execute(
            sa.text("UPDATE raw_transactions SET extra_fields_json = :extra WHERE id = :id"),
            {"extra": json.dumps(extra, ensure_ascii=False), "id": raw_id},
        )

    with op.batch_alter_table('raw_transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_raw_transactions_duplicate_of_transaction_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_raw_transactions_duplicate_of_transaction_id'))
        batch_op.drop_column('kept_by_user')
        batch_op.drop_column('duplicate_of_transaction_id')
