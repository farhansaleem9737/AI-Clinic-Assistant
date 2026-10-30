"""Cloudflare R2 object storage, through R2's S3-compatible API with boto3.

boto3 talks to Cloudflare R2 here, not to Amazon: the endpoint is the R2
account endpoint and the region is "auto". No AWS account is involved.

boto3 is synchronous. Every call that goes over the network runs in
Starlette's worker thread pool (run_in_threadpool), so a slow upload never
blocks the event loop that serves other requests. Generating a presigned
URL is local HMAC signing with no network call, so it runs inline.

Never log a presigned URL (its query string *is* the credential), file
contents, or the settings object.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import StorageUnavailableError 

logger = logging.getLogger(__name__)

# Error codes R2 returns for an object that does not exist 
_MISSING = {"404","NoSuchKey","NotFound"}

class StorageError(Exception):
    """R2 failed or refused a request. Internal: services translate it into a DomainError, so it never reaches a client as-is."""

    def  __init__(self, operation:str, code : str | None=None )->None:
        super().__init__(f"{operation} failed"+(f"({code})" if code else ""))
        self.operation=operation
        self.code=code


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None


class Storage(Protocol):
    """What the services need from object storage: R2Storage in the app, an
    in-memory fake in tests."""
    bucket: str

    async def put(self, key: str, data: bytes, *, content_type: str)-> None:...

    async def head(self, key:str) -> ObjectInfo | None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    def presigned_get_url(
    self, key: str, *, expires_in: int, download_name: str | None = None, content_type: str | None = None
    ) -> str: ...


class R2Storage:
    def __init__(
            self, *, endpoint_url: str, access_key_id: str, secret_access_key: str, bucket: str, region: str = "auto",timeout: int =10,
    )-> None:
        self.bucket=bucket
        self._client=boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                signature_version="s3v4",
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts":3, "mode":"standard"},
                # Recent boto3 releases add CRC checksum headers to every upload
                # by default. Send them only when an operation requires them.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await self._call("put_object",Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def head(self, key: str) -> ObjectInfo | None:
        """Size and type of an object, or none when it  ddoes not exist"""
        try:
            response= await self._call("head_object", Bucket=self.bucket, Key=key)
        except StorageError as exc:
            if exc.code in _MISSING:
                return None
            raise
        return ObjectInfo(size=response["ContentLength"], content_type=response.get("ContentType"))

    async def get(self, key: str) -> bytes:
        """The object's bytes, read on the server (e.g. to pass an image to the AI provider, D96)."""
        response = await self._call("get_object", Bucket=self.bucket, Key=key)
        return await run_in_threadpool(response["Body"].read)

    async def delete(self, key: str)-> None:
        # Deleting a key that does not exist succeeds, so retrying is safe.
        await self._call("delete_object", Bucket=self.bucket, Key=key)

    def  presigned_get_url(
            self, key: str, *, expires_in: int, download_name: str | None = None, content_type: str | None = None   
    ) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if download_name:
            # The browser saves the file instead of rendering it from R2
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        if content_type:
            params["ResponseContentType"]=content_type
        return self._client.generate_presigned_url("get_object",Params=params, ExpiresIn=expires_in)
    def close(self) -> None:
        self._client.close()

    async def _call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        try:
            return await run_in_threadpool(getattr(self._client, operation), **kwargs)
        except ClientError as exc:
            # R2 answered with an error: access denied bad signature, missing key ...
            code = str(exc.response.get("Error",{}).get("Code","")) or None
            if code not in _MISSING:
                logger.warning(
                    "storage_request_failed",
                    extra={
                        "operation": operation,
                        "code":  code,
                        "status": exc.response.get("ResponseMetadata",{}).get("HTTPStatusCode"),
                    },
                )
            raise StorageError(operation, code) from exc
        except BotoCoreError as exc:
            #  No answer at all: timeout, DNS or  connection failure.
            logger.warning("storage_unreachable", extra={"operation": operation, "error":type(exc).__name__})
            raise StorageError(operation) from exc


@lru_cache(maxsize=1)
def _r2_storage()->R2Storage:
    # One client per process: boto3 clients are thread-safe and keep a
    # connection pool, so creating one per request would waste both.
    return R2Storage(
        endpoint_url=settings.r2_endpoint_url,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        bucket=settings.r2_bucket_name,
        region=settings.r2_region,
        timeout=settings.r2_timeout_seconds,
    )

def get_storage() -> Storage:
    """FastAPI dependency for  endpoints that must store or read files."""
    if not settings.storage_configured:
        raise StorageUnavailableError("File Storage is not configurd", code= "STORAGE_NOT_CONFIGURED")
    return _r2_storage()

def get_optional_storage() -> Storage | None:
    """For responses that merely *show* files (photo URLs): without storage
    they still work, with no photos."""
    return _r2_storage() if settings.storage_configured else None

def close_storage() -> None:
    if _r2_storage.cache_info().currsize:
        _r2_storage().close()
        _r2_storage.cache_clear()