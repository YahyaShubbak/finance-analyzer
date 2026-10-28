from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def write_xlsx(path: Path, headers: list[str], rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path
