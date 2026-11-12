from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import (
    accounts,
    analytics,
    backup,
    budgets,
    categories,
    credit_cards,
    imports,
    points,
    reconciliation,
    recurring,
    rules,
    system,
    transactions,
    transfers,
)
from app.config import APP_VERSION, REPO_ROOT, default_data_dir, settings
from app.db.session import init_db, session_scope
from app.i18n import LanguageMiddleware, tr
from app.security import LocalRequestGuard
from app.services.account_recognition import refresh_signatures
from app.services.backup_service import purge_leftover_restore_dirs
from app.services.card_bill_linking import link_card_bills
from app.services.import_staging import purge_stale_staging_files
from app.services.location_service import refresh_outdated_locations
from app.services.points_service import backfill_points
from app.services.rule_service import apply_rule_updates
from app.services.statement_refresh import refresh_statement_totals
from app.services.transfer_marking import settle_flagged_transfers
from app.services.twin_merge import merge_cross_file_twins

logger = logging.getLogger("finance")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_directories()
    init_db()
    if settings.using_legacy_layout:
        logger.warning(
            "Using the legacy data directory inside the source checkout (%s). "
            "Re-run the install script to move it to %s.",
            settings.data_dir, default_data_dir(),
        )
    purge_stale_staging_files()
    purge_leftover_restore_dirs()
    with session_scope() as session:
        refresh_outdated_locations(session)
        settle_flagged_transfers(session)
        link_card_bills(session)
        apply_rule_updates(session)
        backfill_points(session)
        refresh_statement_totals(session)
        refresh_signatures(session)
        merge_cross_file_twins(session)
    yield


app = FastAPI(title="Local Finance Analyzer", version=APP_VERSION, lifespan=lifespan)


@app.exception_handler(OverflowError)
async def _number_too_large(_request, _exc: OverflowError):
    # e.g. an id or amount beyond SQLite's 64-bit integers in a request
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=422, content={"detail": tr("A number in the request is too large.")})

# No CORS middleware on purpose: the frontend is served by this same
# process (and proxied by Vite in development), so no legitimate caller is
# ever cross-origin. See app.security for the CSRF/DNS-rebinding guard.
app.add_middleware(LocalRequestGuard)
# Accept-Language decides the language of messages (see app.i18n).
app.add_middleware(LanguageMiddleware)

app.include_router(accounts.router)
app.include_router(imports.router)
app.include_router(transactions.router)
app.include_router(analytics.router)
app.include_router(credit_cards.router)
app.include_router(reconciliation.router)
app.include_router(transfers.router)
app.include_router(backup.router)
app.include_router(budgets.router)
app.include_router(categories.router)
app.include_router(recurring.router)
app.include_router(rules.router)
app.include_router(points.router)
app.include_router(system.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


class SPAStaticFiles(StaticFiles):
    """Serves the built frontend. Unknown non-API paths without a file
    extension (client-side routes such as /transactions or
    /reconciliation/3) fall back to index.html, so reloading a page or
    opening a bookmark works instead of returning 404."""

    async def get_response(self, path, scope):
        # StaticFiles hands over an os.path.normpath'ed path, i.e. with
        # backslashes on Windows ("assets\\app.js"): the "/" checks below
        # then never matched there, so assets lost their cache header and an
        # unknown /api/... path fell back to index.html instead of a 404.
        route = path.replace("\\", "/")
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._is_client_route(route):
                raise
            response = await super().get_response("index.html", scope)
        if route.startswith("assets/"):
            # Vite fingerprints asset file names, so they never change.
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        elif response.media_type == "text/html":
            response.headers["cache-control"] = "no-cache"
        return response

    @staticmethod
    def _is_client_route(path: str) -> bool:
        first = path.split("/", 1)[0]
        last = path.rsplit("/", 1)[-1]
        return first not in ("api", "assets") and "." not in last


# API routes are registered above and therefore take priority over the
# static catch-all below.
_FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
