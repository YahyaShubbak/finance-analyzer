"""import ids are never used again

An import's id is what "Undo" and "Remove" send to the server. SQLite gives
a new row the highest id + 1, so after the newest import was removed, the
next one got its id — and a card or window still showing the removed import
then removed the new one. With AUTOINCREMENT an id is never given twice.

SQLite can only add that by rebuilding the table (same columns, indexes and
rows; the ids stay as they are).

Revision ID: e3a91f5c7d08
Revises: b7d3e9a41c52
Create Date: 2026-11-11 21:00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3a91f5c7d08'
down_revision: Union[str, Sequence[str], None] = 'b7d3e9a41c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None, recreate='always',
                              table_kwargs={'sqlite_autoincrement': True}):
        pass


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None, recreate='always',
                              table_kwargs={'sqlite_autoincrement': False}):
        pass
