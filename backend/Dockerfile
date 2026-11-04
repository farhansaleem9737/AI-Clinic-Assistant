# Production image for Render (docs/DEPLOYMENT_READINESS.md, render.yaml).
# Build context: backend/
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Every pinned package ships a manylinux wheel for CPython 3.14, so no
# compiler is needed; --only-binary makes a missing wheel fail the build
# instead of silently compiling.
COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt

# Application code and migrations only (tests, scripts and .env stay out).
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8080

# One uvicorn process per instance; Render scales by adding instances.
# - PORT is injected by Render (8080 when run elsewhere).
# - exec makes uvicorn PID 1 so it receives SIGTERM and shuts down cleanly
#   (lifespan disposes the DB pool) within the platform's grace period.
# - Only Render's proxy can reach the container, so its X-Forwarded-For
#   is trusted: request.client.host becomes the real client IP, which the
#   rate limiter and refresh-token records use.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" \
    --proxy-headers --forwarded-allow-ips="*" --timeout-graceful-shutdown 8
