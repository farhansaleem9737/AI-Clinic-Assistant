import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import engine
from app.core.storage import close_storage

setup_logging(settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        extra={"environment": settings.environment.value, "cors_origins": settings.cors_origins},
    )
    yield
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
@app.get("/", include_in_schema=False)
def root():
    return {"message": "Clinic AI Assistant API is running"}


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "healthy"}
