"""Builds simple synthetic PDF documents for tests using PyMuPDF.

We don't have real bank/credit-card PDF samples (per the project spec,
never invent a bank-specific layout) — these fixtures exercise the
*generic* layout parsers with plain, realistic-looking statement text.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz


def write_text_pdf(path: Path, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=10)
        y += 14
        if y > 800:
            page = doc.new_page(width=595, height=842)
            y = 50

    doc.save(path)
    doc.close()
    return path


def write_blank_pdf(path: Path) -> Path:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()
    return path


def write_table_pdf(path: Path, rows: list[list[tuple[float, str, str]]], line_height: float = 14) -> Path:
    """A table with real columns: each row is a list of (x, text, align),
    align "l" (x = left edge) or "r" (x = right edge, like amounts). An
    empty row leaves a blank line."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 60.0
    for row in rows:
        for x, text, align in row:
            left = x - fitz.get_text_length(text, fontsize=9) if align == "r" else x
            page.insert_text((left, y), text, fontsize=9)
        y += line_height
        if y > 800:
            page = doc.new_page(width=595, height=842)
            y = 60.0
    doc.save(path)
    doc.close()
    return path
