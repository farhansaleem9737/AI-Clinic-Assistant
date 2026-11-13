import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db import schema_check
from app.db.database import engine
from app.core import loop_monitor
from app.core.storage import close_storage
from app.services.ai import extraction_worker
from app.realtime import capture  # noqa: F401  (installs the commit hooks that publish live events)
from app.realtime.hub import hub

setup_logging(settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        extra={"environment": settings.environment.value, "cors_origins": settings.cors_origins},
    )
    # Log loudly when the database is behind the code's migrations (never changes it).
    await schema_check.check(engine)
    loop_monitor.start()
    yield
    await loop_monitor.stop()
    # Ask open sockets to close (1012): browsers reconnect to the next process and re-read.
    await hub.shutdown()
    extraction_worker.shutdown()
    await engine.dispose()
    close_storage()
    logger.info("shutdown")


app = FastAPI(
    title="Clinic AI Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
# Added last so it is the outermost middleware and wraps everything else.
app.add_middleware(RequestContextMiddleware)

register_exception_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)


# Infrastructure probes stay unversioned: load balancers and uptime checks
# should not have to change when the API version does.
#
# Both are `async def` on purpose (D130): a plain `def` route runs in the worker
# thread pool, so a health check had to wait for a free thread and then win the
# interpreter lock back from whatever CPU work was running. These answer on the
# event loop at once, touch nothing (no database, storage or AI), and accept HEAD
# as well as GET, which uptime monitors use.
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root():
    return {"message": "Clinic AI Assistant API is running"}


@app.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
async def health_check():
    # "schema": "behind" means migrations are pending (see the startup log).
    return {"status": "healthy", "schema": schema_check.state["status"]}
