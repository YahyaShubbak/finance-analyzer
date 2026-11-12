"""IBANs in the text of statements and exports: finding them, and telling
them from other codes that look alike."""
from __future__ import annotations

import re

# from Norway's 15 characters to 34 (the check digits tell an IBAN from other codes)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")


def valid_iban(text: str) -> str | None:
    iban = re.sub(r"\s+", "", text).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return None
    digits = "".join(str(int(ch, 36)) for ch in iban[4:] + iban[:4])
    return iban if int(digits) % 97 == 1 else None
