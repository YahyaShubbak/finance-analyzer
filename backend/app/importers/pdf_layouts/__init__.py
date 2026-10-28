from app.importers.pdf_layouts.base import BasePDFLayoutParser, PDFParsedLine, PDFParseResult
from app.importers.pdf_layouts.generic_bank import GenericBankStatementLayout
from app.importers.pdf_layouts.generic_credit_card import GenericCreditCardStatementLayout

# New bank/issuer-specific parsers register here. Order doesn't matter —
# the importer picks whichever parser reports the highest detect()
# confidence above the selection threshold.
LAYOUT_REGISTRY: list[BasePDFLayoutParser] = [
    GenericCreditCardStatementLayout(),
    GenericBankStatementLayout(),
]

__all__ = [
    "BasePDFLayoutParser",
    "PDFParsedLine",
    "PDFParseResult",
    "LAYOUT_REGISTRY",
]
