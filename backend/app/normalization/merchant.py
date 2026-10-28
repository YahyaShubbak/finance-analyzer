"""Merchant normalization.

Deterministic, rule-based (no LLM). Rules live in the merchant_rules table
so user corrections persist across restarts and re-imports. Built-in
default rules are marked is_user_defined=False and are synchronized with
DEFAULT_MERCHANT_RULES on every import, so improving a built-in rule in a
new version also fixes existing installations; user-defined rules are
never touched by that and always take precedence.

Rules are matched against the counterparty (payee/payer column, when the
export has one) together with the description, since e.g. a PayPal
payment's actual merchant is often only named in the purpose text.
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

from app.db.models import MerchantRule

# Word boundaries (\b) matter: "rewe" must not match "Brewery".
DEFAULT_MERCHANT_RULES: list[tuple[str, str]] = [
    (r"\bamazon prime\b|\bprime video\b|\bamzn prime\b", "Amazon Prime"),
    (r"\bamzn\b|\bamazon\b", "Amazon"),
    (r"\bnetflix\b", "Netflix"),
    (r"\bspotify\b", "Spotify"),
    (r"\bpaypal\b", "PayPal"),
    (r"\blidl\b", "Lidl"),
    (r"\baldi\b", "Aldi"),
    (r"\brewe\b", "REWE"),
    (r"\bedeka\b", "Edeka"),
    (r"deutsche bahn|\bdb bahn\b|\bdb vertrieb\b", "Deutsche Bahn"),
    (r"\buber\b", "Uber"),
    (r"\bstarbucks\b", "Starbucks"),
    (r"\bapple\.com\b|\bapple store\b", "Apple"),
    (r"\bgoogle \*|\bgoogle pay\b", "Google"),
]


def sync_default_merchant_rules(session: Session) -> None:
    """Make the built-in rules in the database match DEFAULT_MERCHANT_RULES
    exactly (add new ones, drop ones removed or rewritten in this version).
    User-defined rules are left alone."""
    existing = session.exec(select(MerchantRule).where(MerchantRule.is_user_defined == False)).all()  # noqa: E712
    wanted = dict(DEFAULT_MERCHANT_RULES)
    changed = False
    kept: set[str] = set()
    for rule in existing:
        if wanted.get(rule.pattern) != rule.normalized_merchant or not rule.is_regex or rule.pattern in kept:
            session.delete(rule)  # outdated, or a copy left by concurrent requests
            changed = True
        else:
            kept.add(rule.pattern)
    for pattern, normalized in DEFAULT_MERCHANT_RULES:
        if pattern not in kept:
            session.add(MerchantRule(pattern=pattern, is_regex=True, normalized_merchant=normalized))
            changed = True
    if changed:
        session.commit()



def _match_text(description: str | None, counterparty: str | None) -> str:
    return " ".join(part for part in (counterparty, description) if part)


def normalize_merchant(
    description: str | None, rules: list[MerchantRule], counterparty: str | None = None
) -> str | None:
    """Apply rules in order (user-defined rules first, so manual corrections
    always win over built-in defaults) and return the normalized merchant
    name, or a cleaned-up version of the counterparty/description if
    nothing matches."""
    text = _match_text(description, counterparty)
    if not text:
        return None

    # PayPal hides the real merchant behind itself: "PAYPAL *SPOTIFY" (card)
    # or "... Ihr Einkauf bei AMAZON" (direct debit). Name that merchant.
    behind = _PAYPAL_MERCHANT_RE.search(text)
    if behind:
        inner = normalize_merchant((behind.group("merchant") or behind.group("merchant2") or behind.group("merchant3") or "").strip(" ,;"),
                                   rules)
        if inner and not re.fullmatch(r"(?i)paypal|sumup|amz|i?zettle", inner):
            return inner

    ordered = sorted(rules, key=lambda r: (not r.is_user_defined, r.id or 0))
    lowered = text.lower()
    for rule in ordered:
        try:
            if rule.is_regex:
                if re.search(rule.pattern, text, re.IGNORECASE):
                    return rule.normalized_merchant
            # a plain pattern must match whole words: "Rewe" is not in "Brewery"
            elif re.search(rf"(?<!\w){re.escape(rule.pattern.lower())}(?!\w)", lowered):
                return rule.normalized_merchant
        except re.error:
            continue

    return _fallback_clean(counterparty or description or "")


# Payment services and marketplaces print the actual merchant after a "*":
# "PAYPAL *SPOTIFY", "SumUp *Cafe Beispiel", "AMZ*Beispiel Versand" (a seller on
# Amazon's marketplace). An order number there ("AMZN Mktp DE*MH2UF83Y4") is no merchant.
_PAYPAL_MERCHANT_RE = re.compile(
    r"\b(?:paypal|sumup|amz|zettle|izettle)\s*\*\s*(?P<merchant>(?![A-Z0-9]*\d)[^\s*][^*]*?)(?:\s{2,}|\s+\d{4,}|$)"
    r"|ihr einkauf bei\s+(?P<merchant2>[^,.;]+)"
    # a payment app: "<PROGRAM> PAY / dm-drogerie markt / <processor>"
    r"|\b[a-z]+ pay\s*/\s*(?P<merchant3>[^/]+?)\s*(?:/|$)",
    re.IGNORECASE,
)


def _fallback_clean(description: str) -> str | None:
    """Best-effort generic cleanup when no rule matches: strip common noise
    like card terminal codes, trailing reference numbers, excess whitespace."""
    text = description.strip()
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\b\d{6,}\b", "", text)          # long numeric references
    text = re.sub(r"[*#]\S+$", "", text)              # trailing *12345 codes
    text = text.strip(" -*#")
    return text or description.strip() or None
