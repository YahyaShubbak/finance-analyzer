"""User-facing messages in the language chosen in the UI (German or English).

Messages are written in English in the code; the English text is also the
lookup key for the German catalog (``app.i18n_de.DE``)::

    raise ImportServiceError(tr("Account {id} not found.", id=account_id))

The frontend sends ``Accept-Language`` with every request;
``LanguageMiddleware`` keeps the chosen language for the duration of that
request. Outside a request (CLI, tests, startup) messages stay English.

Texts that are stored in the database (e.g. a transaction's review reason)
are stored in English and translated when they are sent to the UI, so a
later language switch applies to them too.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.i18n_de import DE

SUPPORTED_LANGUAGES = ("en", "de")
DEFAULT_LANGUAGE = "en"

_language: ContextVar[str] = ContextVar("language", default=DEFAULT_LANGUAGE)


def parse_accept_language(header: str | None) -> str:
    """The supported language the client prefers most: "de-DE,de;q=0.9,en;q=0.8"
    -> "de". Unknown or missing -> English."""
    best, best_q = DEFAULT_LANGUAGE, -1.0
    for part in (header or "").split(","):
        tag, _, params = part.strip().partition(";")
        language = tag.strip().lower().split("-")[0]
        if language not in SUPPORTED_LANGUAGES:
            continue
        q = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q > 0 and q > best_q:  # q=0: "not acceptable"; equal weights: the earlier entry wins
            best, best_q = language, q
    return best


@contextmanager
def use_language(language: str) -> Iterator[None]:
    token = _language.set(language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE)
    try:
        yield
    finally:
        _language.reset(token)


def tr(message: str, /, **params: object) -> str:
    """``message`` (English, with ``{name}`` placeholders) in the current
    language, placeholders filled from ``params``."""
    template = DE.get(message, message) if _language.get() == "de" else message
    return template.format(**params) if params else template


def format_amount(minor: int, currency: str = "EUR") -> str:
    """12345 -> "123,45 €" (German) / "€123.45" (English)."""
    value = f"{abs(minor) / 100:,.2f}"
    sign = "-" if minor < 0 else ""
    symbol = "€" if currency == "EUR" else currency
    if _language.get() == "de":
        value = value.replace(",", "\u2009").replace(".", ",").replace("\u2009", ".")
        return f"{sign}{value} {symbol}"
    return f"{sign}{symbol}{value}" if symbol == "€" else f"{sign}{value} {symbol}"


def format_date(value) -> str:
    """A date, or a naive UTC timestamp shown in local time, as the UI writes it."""
    from datetime import UTC, datetime

    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC).astimezone().date() if value.tzinfo is None else value.astimezone().date()
    return value.strftime("%d.%m.%Y") if _language.get() == "de" else value.isoformat()


class LanguageMiddleware:
    """Pure ASGI middleware: the request's Accept-Language decides the
    language of every message produced while handling it."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = next((value.decode("latin-1") for key, value in scope["headers"] if key == b"accept-language"), None)
        token = _language.set(parse_accept_language(header))
        try:
            await self.app(scope, receive, send)
        finally:
            _language.reset(token)
