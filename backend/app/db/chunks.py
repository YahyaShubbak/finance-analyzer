"""SQLite accepts at most 32,766 values in one query, so a long id list in
`column.in_(ids)` fails ("too many SQL variables"). Query in chunks."""
from __future__ import annotations

from collections.abc import Iterable, Iterator

CHUNK_SIZE = 900


def chunked(ids: Iterable[int], size: int = CHUNK_SIZE) -> Iterator[list[int]]:
    batch: list[int] = []
    for value in ids:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
