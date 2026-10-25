import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.assets import router as assets_router
from app.api.auth import require_auth
from app.api.auth import router as auth_router
from app.api.auto_open import router as auto_open_router
from app.api.chart import router as chart_router
from app.api.decisions import router as decisions_router
from app.api.health import router as health_router
from app.api.papers import router as papers_router
from app.api.portfolio import router as portfolio_router
from app.api.positions import router as positions_router
from app.api.reset import router as reset_router
from app.api.settings import router as settings_router
from app.api.system_health import router as system_health_router
from app.notifications.error_reporting import setup_logging

setup_logging("api")
logger = logging.getLogger(__name__)

# No /docs, /redoc or /openapi.json: the API map is nobody's business.
app = FastAPI(title="Trading App API", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception) -> JSONResponse:
    """Any unhandled error: a plain 500 for the client, the traceback to the
    log and (via the error forwarder) to Telegram. 4xx responses are not
    errors and aren't reported."""
    logger.error("%s %s failed", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# Public: health check and login. Everything else needs a login token.
app.include_router(health_router)
app.include_router(auth_router)

for router in (
    assets_router,
    auto_open_router,
    chart_router,
    decisions_router,
    papers_router,
    portfolio_router,
    positions_router,
    reset_router,
    settings_router,
    system_health_router,
):
    app.include_router(router, dependencies=[Depends(require_auth)])
