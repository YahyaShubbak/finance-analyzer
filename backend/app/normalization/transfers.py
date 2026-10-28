"""Transfer detection.

A transfer is a pair of transactions on two *different* accounts owned by
the same user, in the same currency, with opposite signs, within a small
date window (bank processing delay). Detected pairs are marked as
transfers so they are excluded from income/expense totals.

Deliberately conservative, because a wrong match silently removes a real
expense and a real income from every total:

* amounts must match exactly — a pair with a difference (e.g. a wire
  fee) would drop that difference from every total; naming the other
  account's IBAN only widens the date window;
* a side whose counterparty IBAN is known and is none of the user's
  accounts (when the other account's IBAN is known) paid someone else: no pair;
* the match must be unambiguous from BOTH sides: the positive side must
  be the negative side's single best candidate and vice versa. Ties are
  left unmatched for the user to review.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

DEFAULT_MAX_DAY_GAP = 3
IBAN_MATCH_MAX_DAY_GAP = 5


@dataclass(frozen=True)
class TransferCandidate:
    id: int
    account_id: int
    transaction_date: date
    amount_minor: int
    currency: str = "EUR"
    counterparty_iban: str | None = None


def _names_account(tx: TransferCandidate, other: TransferCandidate, ibans: dict[int, str]) -> bool:
    other_iban = ibans.get(other.account_id)
    return bool(other_iban and tx.counterparty_iban and tx.counterparty_iban == other_iban)


def _names_someone_else(tx: TransferCandidate, other: TransferCandidate, ibans: dict[int, str]) -> bool:
    """tx was paid to/from an IBAN that is none of the user's accounts (while
    the other account's IBAN is known) — a landlord, a friend."""
    other_iban = ibans.get(other.account_id)
    return bool(other_iban and tx.counterparty_iban and tx.counterparty_iban not in ibans.values())


def find_transfer_pairs(
    candidates: list[TransferCandidate],
    max_day_gap: int = DEFAULT_MAX_DAY_GAP,
    account_ibans: dict[int, str] | None = None,
) -> list[tuple[int, int]]:
    """Return (negative_id, positive_id) pairs. Each id appears at most once."""
    ibans = account_ibans or {}
    positives_by_key: dict[tuple[str, int], list[TransferCandidate]] = defaultdict(list)
    for c in candidates:
        if c.amount_minor > 0:
            positives_by_key[(c.currency, c.amount_minor)].append(c)
    negatives = [c for c in candidates if c.amount_minor < 0]

    # Score every plausible edge; lower is better.
    edges: dict[int, list[tuple[tuple, int]]] = defaultdict(list)  # neg id -> [(score, pos id)]
    reverse: dict[int, list[tuple[tuple, int]]] = defaultdict(list)  # pos id -> [(score, neg id)]

    def add_edge(neg: TransferCandidate, pos: TransferCandidate, iban_link: bool) -> None:
        amount_diff = abs(pos.amount_minor + neg.amount_minor)
        date_gap = abs((pos.transaction_date - neg.transaction_date).days)
        score = (amount_diff, 0 if iban_link else 1, date_gap)
        edges[neg.id].append((score, pos.id))
        reverse[pos.id].append((score, neg.id))

    for neg in negatives:
        for pos in positives_by_key.get((neg.currency, -neg.amount_minor), []):
            if pos.account_id == neg.account_id:
                continue
            if _names_someone_else(neg, pos, ibans) or _names_someone_else(pos, neg, ibans):
                continue  # paid to / received from a third party
            iban_link = _names_account(neg, pos, ibans) or _names_account(pos, neg, ibans)
            gap_limit = IBAN_MATCH_MAX_DAY_GAP if iban_link else max_day_gap
            if abs((pos.transaction_date - neg.transaction_date).days) <= gap_limit:
                add_edge(neg, pos, iban_link)

    def unique_best(options: list[tuple[tuple, int]]) -> int | None:
        options = sorted(options)
        if not options or (len(options) > 1 and options[0][0] == options[1][0]):
            return None
        return options[0][1]

    pairs: list[tuple[int, int]] = []
    used: set[int] = set()
    for neg in sorted(negatives, key=lambda c: (c.transaction_date, c.id)):
        pos_id = unique_best(edges.get(neg.id, []))
        if pos_id is None or pos_id in used or neg.id in used:
            continue
        if unique_best(reverse.get(pos_id, [])) != neg.id:
            continue  # the positive side has an equally good (or better) other partner
        used.update((neg.id, pos_id))
        pairs.append((neg.id, pos_id))
    return pairs
