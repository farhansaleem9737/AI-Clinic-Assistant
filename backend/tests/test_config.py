import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from app.db.database import engine

REQUIRED = {"database_url": "postgresql+asyncpg://u:p@h/db", "secret_key": "k"}


def test_cors_origins_parse_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example, https://b.example ,")
    settings = Settings(_env_file=None, **REQUIRED)
    assert settings.cors_origins == ["http://a.example", "https://b.example"]


def test_wildcard_cors_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **REQUIRED)


def test_safe_defaults(monkeypatch):
    for name in ("CORS_ORIGINS", "SQL_ECHO", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None, **REQUIRED)
    assert settings.sql_echo is False
    assert settings.cors_origins == []
    assert settings.environment is Environment.development


def test_engine_does_not_echo_sql():
    assert engine.echo is False


async def test_cors_allows_configured_origin(client):
    response = await client.options(
        "/api/v1/departments/",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_cors_blocks_unknown_origin(client):
    response = await client.options(
        "/api/v1/departments/",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers
