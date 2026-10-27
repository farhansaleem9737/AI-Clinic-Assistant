"""The R2 client without any network: botocore's Stubber answers in R2's place."""

from urllib.parse import parse_qs, urlparse

import pytest
from botocore.stub import Stubber

from app.core.storage import R2Storage, StorageError


def make_storage() -> R2Storage:
    return R2Storage(
        endpoint_url="https://" + "a" * 32 + ".r2.cloudflarestorage.com",
        access_key_id="test-key",
        secret_access_key="test-secret",
        bucket="test-bucket",
        timeout=2,
    )


async def test_missing_object_is_none():
    storage = make_storage()
    with Stubber(storage._client) as stub:
        stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
        assert await storage.head("nope.pdf") is None


async def test_existing_object_reports_size_and_type():
    storage = make_storage()
    with Stubber(storage._client) as stub:
        stub.add_response(
            "head_object",
            {"ContentLength": 5, "ContentType": "application/pdf"},
            {"Bucket": "test-bucket", "Key": "a.pdf"},
        )
        info = await storage.head("a.pdf")
    assert (info.size, info.content_type) == (5, "application/pdf")


@pytest.mark.parametrize("code", ["InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"])
async def test_rejected_credentials_raise_storage_error(code):
    storage = make_storage()
    with Stubber(storage._client) as stub:
        stub.add_client_error("put_object", service_error_code=code, http_status_code=403)
        with pytest.raises(StorageError) as exc:
            await storage.put("k.txt", b"x", content_type="text/plain")
    assert exc.value.code == code


def test_presigned_url_expires_and_forces_download():
    url = make_storage().presigned_get_url(
        "patient-documents/p/f.pdf",
        expires_in=300,
        download_name="lab_report-2026-10-01.pdf",
        content_type="application/pdf",
    )
    query = parse_qs(urlparse(url).query)
    assert query["X-Amz-Expires"] == ["300"]
    assert "X-Amz-Signature" in query
    assert query["response-content-disposition"] == ['attachment; filename="lab_report-2026-10-01.pdf"']
    assert "test-secret" not in url
