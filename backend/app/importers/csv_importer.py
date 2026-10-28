"""Generic CSV importer.

Tolerant of: different delimiters, UTF-8/Windows encodings, metadata lines
before the header row, decimal comma or point, and varying column names.
All interpretation happens in app.importers.tabular (shared with XLSX);
this module only turns bytes into rows of text cells.
"""
from __future__ import annotations

import csv
import hashlib
import io

import chardet

from app.importers.base import BaseImporter, ParsedImport
from app.importers.tabular import MAX_TABLE_CELLS, MAX_TABLE_ROWS, parse_rows, too_large

_CANDIDATE_DELIMITERS = [";", ",", "\t", "|"]


_MAX_FIELD_BYTES = 16 * 1024 * 1024


class CSVImporter(BaseImporter):
    def can_handle(self) -> bool:
        return self.file_path.suffix.lower() == ".csv"

    @staticmethod
    def _decode(raw: bytes) -> str:
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
        detected = chardet.detect(raw[:200_000])
        encoding = detected.get("encoding")
        if encoding and (detected.get("confidence") or 0) >= 0.8:
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                pass
        # German bank exports that aren't UTF-8 are practically always
        # Windows-1252/Latin-1; cp1252 decodes any byte sequence.
        return raw.decode("cp1252", errors="replace")

    @staticmethod
    def _sniff_delimiter(text: str) -> str:
        lines = [line for line in text.splitlines()[:60] if line.strip()]
        sample = "\n".join(lines)
        try:
            return csv.Sniffer().sniff(sample, delimiters="".join(_CANDIDATE_DELIMITERS)).delimiter
        except csv.Error:
            # Pick the delimiter that splits the most lines into the same
            # (>1) number of fields — robust against preamble lines.
            def consistency(delimiter: str) -> int:
                counts = [len(next(csv.reader([line], delimiter=delimiter))) for line in lines]
                common = max(set(counts), key=counts.count) if counts else 1
                return counts.count(common) if common > 1 else 0

            return max(_CANDIDATE_DELIMITERS, key=consistency)

    def parse(self) -> ParsedImport:
        raw_bytes = self.file_path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        text = self._decode(raw_bytes)
        delimiter = self._sniff_delimiter(text)
        csv.field_size_limit(max(csv.field_size_limit(), _MAX_FIELD_BYTES))  # a long note in one cell
        rows, cells = [], 0
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            rows.append(row)
            cells += len(row)
            if len(rows) > MAX_TABLE_ROWS or cells > MAX_TABLE_CELLS:
                return too_large(self.original_filename, checksum)
        return parse_rows(rows, filename=self.original_filename, checksum=checksum, options=self.options)
