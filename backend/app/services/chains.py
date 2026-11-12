"""Chains: one payee behind many branch texts.

Card statements name the shop with its branch: "MERCADONA C/JACA VALENCIA",
"MERCADONA AV.DE FRANCIA VALENCIA", "ROSSMANN KASSEL". Each text is a payee
of its own to rule_service.derive_category_pattern, so a learned category
covered one branch only and the review queue asked once per branch.

Found from the user's own bookings, without a list of names: each payee
text is cut where its branch part starts — a known town, a street ("C/",
"AV.", "PZA.", "CALLE", "STR."), a number, a legal form ("GMBH"), "FILIALE",
"STATION", a "*reference". A name left over that begins several payee texts,
at least one of which really had a branch part cut off, is a chain. A lone
everyday word is never one: "STADT KASSEL" and "STADT BIELEFELD" stay apart,
as do "DEUTSCHE BAHN" and "DEUTSCHE BANK" (nothing was cut from them).
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

from app.db.models import Transaction

# words that name a kind of place, not a payee: never a chain on their own
_GENERIC = frozenset("""
    stadt gemeinde kreis landkreis land bund hotel hostel pension cafe café bar restaurant restaurante
    ristorante pizzeria bistro imbiss bäckerei backerei baeckerei konditorei metzgerei apotheke farmacia
    kiosk tankstelle raststaette raststätte parkhaus parking taxi museum museo kino cine praxis dr
    deutsche bank sparkasse volksbank universitaet universität hochschule e.s. es la el le les los las
    der die das the il lo uni universitat stadtkasse kreiskasse gemeindekasse rist. rest. cafeteria
    panaderia panadería supermercado
""".split())
# small words between the words of a name: never a town, never the end of a chain's name
_FILLERS = frozenset("de del la las los el le les du des der die das und y e et the of di da im am an in zum zur bei".split())
_LEGAL = frozenset("""
    gmbh ag kg ohg ug se sl s.l. sa s.a. sas sarl s.a.r.l. n.v. nv bv b.v. ltd inc llc e.k. e.v. co.kg & mbh
""".split())
# where a street or branch part starts: "C/JACA", "AV.DE", "V.AVDA.MALVAROSA", "PZA.", "STR."
_BRANCH_RE = re.compile(
    r"(?i)(?:^|[./])(?:c/|avda?\b|avd\b|av\.|pza\b|pl\.|plaza\b|calle\b|cl\b|ctra\b|str\b|strasse\b|straße\b)"
    r"|^(?:fil\.?|filiale|station|tankstelle|nr\.?|no\.)$"
)


def _is_town(word: str) -> bool:
    from app.normalization.location import _NOT_A_TOWN, _places, place_key

    # "MAINZ-KOSTHEIM", "LEIPZIG/CONNEWI": the town comes first; very short
    # words are a town somewhere far too often
    key = place_key(re.split(r"[-/]", word)[0])
    return len(key) >= 4 and key not in _NOT_A_TOWN and key in _places()


def _branch_word(word: str) -> bool:
    lowered = word.lower().strip(",;:")
    return any(ch.isdigit() for ch in word) or word.startswith("*") or lowered in _LEGAL or bool(_BRANCH_RE.search(word))


def stem(pattern: str) -> tuple[str, bool]:
    """(the payee text without its branch part, whether one was cut off).
    A town only counts at the end ("ROSSMANN DRESDEN", "PENNY KASSEL
    NIEDERZWEH KASSEL"): inside a name a word may happen to be a town
    somewhere in the world."""
    words = pattern.split()
    tail = list(words)
    while len(tail) > 1 and _branch_word(tail[-1]):
        tail.pop()
    ends_with_town = len(tail) > 1 and tail[-1].lower() not in _FILLERS and _is_town(tail[-1])
    for i, word in enumerate(words[1:], start=1):
        town = ends_with_town and word.lower() not in _FILLERS and _is_town(word)
        if _branch_word(word) or town:
            kept = words[:i]
            while len(kept) > 1 and kept[-1].lower().strip(",;:-/") in _FILLERS:
                kept.pop()
            if len(kept) == 1 and kept[0].lower() in _GENERIC:
                return pattern, False  # "STADT KASSEL": the town is the name
            return " ".join(kept).rstrip(",;:-/"), True
    return pattern, False


def _qualifies(name: str) -> bool:
    """A chain's name needs a word of its own, not just "CAFE DE"."""
    return any(len(re.sub(r"[^a-zäöüß]", "", w)) >= 3 and w not in _GENERIC and w not in _FILLERS
               for w in name.lower().split())


def find_chains(patterns: set[str]) -> dict[str, str]:
    """payee pattern (upper case) -> its chain's name: the pattern's leading
    words, as printed (only patterns that belong to a chain)."""
    originals = {p.upper(): p for p in patterns}
    stems = {key: stem(p) for key, p in originals.items()}
    evidence = {s.upper() for s, cut in stems.values() if cut}  # a branch part really was cut off
    chains = {s for s in evidence if _qualifies(s)}

    out: dict[str, str] = {}
    for key, (s, _cut) in stems.items():
        words = s.upper().split()
        # the shortest chain name this payee's text begins with
        for n in range(1, len(words) + 1):
            candidate = " ".join(words[:n])
            if candidate in chains and _members(candidate, stems) >= 2:
                out[key] = " ".join(originals[key].split()[:n]).rstrip(",;:-/")
                break
    return out


def _members(chain: str, stems: dict[str, tuple[str, bool]]) -> int:
    prefix = chain + " "
    return sum(1 for s, _ in stems.values() if s.upper() == chain or s.upper().startswith(prefix))


def chain_index(session: Session) -> dict[str, str]:
    """For every payee in the user's bookings: its chain, where it has one.
    Read from every booking, so remembered until the data changes (the
    review queue asks for it with every page, learning with every click)."""
    from app.db.session import remembered

    # (it reads the bookings' merchant and description only)
    return remembered(session, "chain_index", lambda: _chain_index(session), payees_only=True)


def _chain_index(session: Session) -> dict[str, str]:
    from app.services.rule_service import derive_category_pattern

    patterns = set()
    for merchant, description in session.exec(
        select(Transaction.merchant, Transaction.normalized_description).distinct()
    ).all():
        pattern = derive_category_pattern(merchant or description or "")  # as category_rule_source picks it
        if pattern:
            patterns.add(pattern)
    return find_chains(patterns)


def payee_name(tx: Transaction, chains: dict[str, str]) -> str | None:
    """Who was paid, as a learned category names it: the payee's chain
    ("MERCADONA"), else its own name ("Kiosk Sonnenschein"); None when the
    text names no payee (a bare "PayPal" line). The one definition used for
    review groups, learned rules and card issuers."""
    from app.services.rule_service import category_rule_source, derive_category_pattern

    _field, source = category_rule_source(tx)
    pattern = derive_category_pattern(source)
    return chains.get(pattern.upper(), pattern) if pattern else None
