"""Protection for a local, unauthenticated web app against the browser.

Binding to 127.0.0.1 keeps other machines out, but every web page the user
visits runs code on the same machine and can send requests to
``http://127.0.0.1:8420``. Two attacks matter:

* **CSRF** — a foreign page submits a form (or a ``no-cors`` fetch) to a
  state-changing endpoint, e.g. restoring an attacker-supplied backup.
  Browsers send such "simple" requests without any CORS preflight.
* **DNS rebinding** — a foreign domain is re-pointed to 127.0.0.1, so the
  browser treats the app as same-origin with the attacker's page and lets
  it *read* every response (all financial data).

Defences, applied to every request by ``LocalRequestGuard``:

1. The ``Host`` header must name this machine (defeats DNS rebinding —
   the rebound request still carries the attacker's hostname).
2. State-changing requests (anything but GET/HEAD/OPTIONS) must carry the
   custom ``X-Finance-Client`` header. A cross-origin page can only add a
   custom header after a CORS preflight, and this app answers no
   preflight, so the request never gets sent.
3. If the browser reports the request's origin (``Origin`` or
   ``Sec-Fetch-Site``), it must be this app itself or the Vite dev server.
4. Reading the API from another website is refused too (``Sec-Fetch-Site:
   cross-site``, ``Cross-Origin-Resource-Policy``): a page must not even
   embed a statement's page image to probe which imports exist.

Non-browser clients (curl, scripts) just need to send the header, e.g.
``curl -H 'X-Finance-Client: 1' -X POST http://127.0.0.1:8420/api/...``.
"""
from __future__ import annotations

import json
import re

from app.config import settings

CLIENT_HEADER = "x-finance-client"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_DEV_SERVER_PORTS = (5173,)

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        b"img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        b"base-uri 'none'; form-action 'self'; object-src 'none'",
    ),
]


# The whole header must be "name[:port]" or "[ipv6][:port]" — anything else
# (e.g. "[::1].evil.com") is rejected rather than partially parsed.
_HOST_RE = re.compile(r"^(?:\[(?P<ipv6>[0-9a-f:.]+)\]|(?P<name>[a-z0-9._-]+))(?::\d{1,5})?$")


def _split_host(host_header: str) -> str | None:
    match = _HOST_RE.match(host_header.strip().lower())
    if not match:
        return None
    return match.group("ipv6") or match.group("name")


def _allowed_origins() -> set[str]:
    origins = set()
    for name in settings.allowed_host_names:
        shown = f"[{name}]" if ":" in name else name
        origins.add(f"http://{shown}:{settings.port}")
        for dev_port in _DEV_SERVER_PORTS:
            origins.add(f"http://{shown}:{dev_port}")
    return origins


def check_request(method: str, headers: dict[str, str], path: str = "") -> tuple[int, str] | None:
    """Returns (status, reason) when the request must be rejected, else None.
    Pure function so it can be unit-tested without a server."""
    host = headers.get("host")
    if not host or _split_host(host) not in settings.allowed_host_names:
        return 421, "Invalid Host header. Open the app via http://127.0.0.1 or http://localhost."

    if method.upper() in _SAFE_METHODS:
        if path.startswith("/api/") and headers.get("sec-fetch-site") == "cross-site":
            return 403, "Cross-site requests are not allowed."
        return None

    fetch_site = headers.get("sec-fetch-site")
    if fetch_site == "cross-site":
        return 403, "Cross-site requests are not allowed."

    origin = headers.get("origin")  # "null" (sandboxed iframes, file://) is never allowed
    if origin is not None and origin.lower().rstrip("/") not in _allowed_origins():
        return 403, "Requests from other websites are not allowed."

    if CLIENT_HEADER not in headers:
        return 403, f"Missing {CLIENT_HEADER} header."
    return None


class LocalRequestGuard:
    """Pure ASGI middleware (no request-body buffering, works for uploads)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        rejection = check_request(scope["method"], headers, scope.get("path", ""))
        if rejection is not None:
            status, reason = rejection
            body = json.dumps({"detail": reason}).encode()
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
                + SECURITY_HEADERS,
            })
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [
                    (k, v) for k, v in SECURITY_HEADERS if k not in existing
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
