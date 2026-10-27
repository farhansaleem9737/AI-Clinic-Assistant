import pytest
from pydantic import ValidationError

from app.core.config import Settings

REQUIRED = {"database_url": "postgresql+asyncpg://u:p@h/db", "secret_key": "k"}
ACCOUNT = "0123456789abcdef0123456789abcdef"
R2 = {
    "r2_endpoint_url": f"https://{ACCOUNT}.r2.cloudflarestorage.com",
    "r2_access_key_id": "key-id",
    "r2_secret_access_key": "s3cr3t-value",
    "r2_bucket_name": "bucket",
}


def make(**values) -> Settings:
    return Settings(_env_file=None, **REQUIRED, **values)


def test_storage_is_optional_outside_production():
    assert make().storage_configured is False


def test_full_settings_configure_storage():
    settings = make(**R2, r2_account_id=ACCOUNT)
    assert settings.storage_configured and settings.r2_region == "auto"


def test_env_example_placeholders_count_as_unset():
    settings = make(
        r2_endpoint_url="https://CHANGE_ME_ACCOUNT_ID.r2.cloudflarestorage.com",
        r2_access_key_id="CHANGE_ME",
        r2_secret_access_key="CHANGE_ME",
        r2_bucket_name="CHANGE_ME",
    )
    assert settings.storage_configured is False


@pytest.mark.parametrize(
    "url",
    [
        f"https://{ACCOUNT}.r2.cloudflarestorage.com/bucket",  # bucket in the path
        f"http://{ACCOUNT}.r2.cloudflarestorage.com",  # not https
        "https://s3.amazonaws.com",  # not R2
        f"https://{ACCOUNT}.r2.cloudflarestorageXcom",  # catches an unescaped "."
    ],
)
def test_bad_endpoints_are_rejected(url):
    with pytest.raises(ValidationError):
        make(**{**R2, "r2_endpoint_url": url})


def test_trailing_slash_is_tolerated():
    assert make(**{**R2, "r2_endpoint_url": R2["r2_endpoint_url"] + "/"}).r2_endpoint_url == R2["r2_endpoint_url"]


def test_account_id_must_match_the_endpoint():
    with pytest.raises(ValidationError):
        make(**R2, r2_account_id="f" * 32)


def test_production_requires_storage(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValidationError):
        make()
    assert make(**R2).storage_configured


def test_secret_is_never_printed():
    settings = make(**R2)
    assert "s3cr3t-value" not in repr(settings)
    assert "s3cr3t-value" not in str(settings.model_dump())
