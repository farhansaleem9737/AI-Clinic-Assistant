import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)


def assert_error_shape(body: dict) -> dict:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"]
    return error


@pytest.fixture
async def probe_client():
    """A throwaway app with the real handlers, for errors no real route triggers on demand."""
    probe = FastAPI()
    probe.add_middleware(RequestContextMiddleware)
    register_exception_handlers(probe)

    @probe.get("/integrity")
    async def integrity():
        raise IntegrityError("INSERT ...", {}, Exception("duplicate key (email)=(secret@example.com)"))

    @probe.get("/crash")
    async def crash():
        raise RuntimeError("connection to postgres:hunter2@db failed")

    errors = {
        "notfound": NotFoundError("gone"),
        "conflict": ConflictError("dup"),
        "rule": BusinessRuleError("nope"),
        "auth": AuthenticationError("who"),
        "perm": PermissionDeniedError("no"),
    }

    @probe.get("/domain/{kind}")
    async def domain(kind: str):
        raise errors[kind]

    transport = ASGITransport(app=probe, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("notfound", 404, "NOT_FOUND"),
        ("conflict", 409, "CONFLICT"),
        ("rule", 400, "BUSINESS_RULE_VIOLATION"),
        ("auth", 401, "AUTHENTICATION_FAILED"),
        ("perm", 403, "PERMISSION_DENIED"),
    ],
)
async def test_domain_errors_map_to_status(probe_client, kind, status, code):
    response = await probe_client.get(f"/domain/{kind}")
    assert response.status_code == status
    assert assert_error_shape(response.json())["code"] == code


async def test_integrity_error_is_409_without_driver_text(probe_client):
    response = await probe_client.get("/integrity")
    assert response.status_code == 409
    assert assert_error_shape(response.json())["code"] == "CONFLICT"
    assert "secret@example.com" not in response.text
    assert "INSERT" not in response.text


async def test_unhandled_error_is_generic_500(probe_client):
    response = await probe_client.get("/crash")
    assert response.status_code == 500
    error = assert_error_shape(response.json())
    assert error["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text
    assert "postgres" not in response.text


async def test_validation_error_shape_does_not_echo_password(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "V",
            "last_name": "V",
            "date_of_birth": "1990-01-01",
            "email": "not-an-email",
            "password": "Sup3rSecretValue",
        },
    )
    assert response.status_code == 422
    error = assert_error_shape(response.json())
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["errors"][0]["loc"] == ["body", "email"]
    assert "Sup3rSecretValue" not in response.text


async def test_unknown_route_uses_error_shape_and_request_id(client):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = assert_error_shape(response.json())
    assert response.headers["X-Request-ID"] == error["request_id"]


async def test_missing_token_is_401_with_challenge(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert_error_shape(response.json())
