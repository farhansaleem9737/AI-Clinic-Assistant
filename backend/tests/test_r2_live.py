"""Talks to the real bucket configured in backend/.env. Skipped unless R2_LIVE_TESTS=1.
Use a development bucket: it writes and deletes objects under test/."""

import asyncio
import os
import urllib.error
import urllib.request
import uuid

import pytest
from dotenv import dotenv_values

from app.core.storage import R2Storage, StorageError
from tests.conftest import BACKEND_DIR

pytestmark = pytest.mark.skipif(
    os.environ.get("R2_LIVE_TESTS") != "1", reason="set R2_LIVE_TESTS=1 to use the real bucket"
)


def live_storage(**overrides) -> R2Storage:
    env = dotenv_values(BACKEND_DIR / ".env")
    values = {
        "endpoint_url": env["R2_ENDPOINT_URL"],
        "access_key_id": env["R2_ACCESS_KEY_ID"],
        "secret_access_key": env["R2_SECRET_ACCESS_KEY"],
        "bucket": env["R2_BUCKET_NAME"],
        "region": env.get("R2_REGION") or "auto",
        "timeout": 10,
    }
    return R2Storage(**{**values, **overrides})


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


async def test_round_trip_and_expiry():
    storage = live_storage()
    key = f"test/{uuid.uuid4()}.txt"
    await storage.put(key, b"hello", content_type="text/plain")
    try:
        assert (await storage.head(key)).size == 5
        assert http_status(storage.presigned_get_url(key, expires_in=60)) == 200
        short = storage.presigned_get_url(key, expires_in=1)
        await asyncio.sleep(3)
        assert http_status(short) in (400, 403)  # R2 refuses an expired signature
    finally:
        await storage.delete(key)
    assert await storage.head(key) is None


async def test_wrong_secret_is_rejected():
    storage = live_storage(secret_access_key="0" * 64)
    with pytest.raises(StorageError) as exc:
        await storage.put(f"test/{uuid.uuid4()}.txt", b"x", content_type="text/plain")
    assert exc.value.code in {"SignatureDoesNotMatch", "InvalidAccessKeyId", "AccessDenied", "Unauthorized"}
