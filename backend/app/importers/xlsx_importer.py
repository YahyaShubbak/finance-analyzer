"""XLSX importer.

Uses the same row-based core as CSVImporter (app.importers.tabular). The
only XLSX-specific concerns are choosing the sheet and that a cell can
already be a native typed value (date, number) rather than text — the
tabular core uses those directly, and falls back to the same string
parsers as CSV for text-formatted cells (e.g. "42,90" / "02.01.2026").
"""
from __future__ import annotations

import hashlib

from openpyxl import load_workbook

from app.i18n import tr
from app.importers.base import BaseImporter, ParsedImport
from app.importers.column_detection import detect_header_row
from app.importers.tabular import MAX_TABLE_CELLS, MAX_TABLE_ROWS, _error_result, parse_rows, too_large

_SCAN_ROWS = 30


class XLSXImporter(BaseImporter):
    def can_handle(self) -> bool:
        return self.file_path.suffix.lower() == ".xlsx"

    def parse(self) -> ParsedImport:
        raw_bytes = self.file_path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        def unreadable(exc: Exception) -> ParsedImport:
            return _error_result(self.original_filename, checksum, tr(
                "Could not open the spreadsheet — it may be damaged or not an XLSX file ({error}).",
                error=type(exc).__name__))

        try:
            workbook = load_workbook(self.file_path, data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001 — any unreadable workbook is a user-facing error
            return unreadable(exc)

        try:
            sheets = []
            cells = 0
            for ws in workbook.worksheets:
                rows = []
                for r in ws.iter_rows(values_only=True):
                    rows.append(list(r))
                    cells += len(r)
                    if len(rows) > MAX_TABLE_ROWS or cells > MAX_TABLE_CELLS:
                        return too_large(self.original_filename, checksum)
                if any(c is not None and str(c).strip() for row in rows for c in row):
                    sheets.append(rows)
        except Exception as exc:  # noqa: BLE001 — a damaged sheet: in read-only mode its rows are only read here
            return unreadable(exc)
        finally:
            workbook.close()

        if not sheets:
            return _error_result(self.original_filename, checksum, tr("The spreadsheet is empty."))

        # First sheet that contains a recognizable transaction table;
        # otherwise the first non-empty sheet (-> manual mapping).
        chosen = next((rows for rows in sheets if detect_header_row(rows, _SCAN_ROWS) is not None), sheets[0])
        return parse_rows(chosen, filename=self.original_filename, checksum=checksum, options=self.options)
