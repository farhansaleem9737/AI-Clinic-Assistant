"""Test doubles for file storage. No network, no real bucket."""

import io
import os

from PIL import Image

from app.core.storage import ObjectInfo,  StorageError

PDF_BYTES = b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"


class FakeStorage:
    """In-memory stand-in for R2Storage. Add an operation name to `fail_on`
    ("put", "head", "delete") to make it fail like an R2 outage."""

    bucket= "test-bucket"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_on: set[str] = set()
        self.presigned: list[dict] = []

    def _maybe_fail(self, operation: str) -> None:
        if operation in self.fail_on:
            raise StorageError(operation, "InternalError")

    async def put(self, key, data, *, content_type):
        self._maybe_fail("put")
        self.objects[key]=(data, content_type)

    async def head(self, key):
        self._maybe_fail("head")
        if key not in self.objects:
            return None
        data, content_type= self.objects[key]
        return ObjectInfo(size=len(data), content_type=content_type)

    async def delete(self, key):
        self._maybe_fail("delete")
        self.objects.pop(key, None)

    def presigned_get_url(self, key, *, expires_in, download_name=None, content_type=None):
        self.presigned.append(
            {"key": key, "expires_in": expires_in, "download_name": download_name, "content_type": content_type}
        )
        return f"https://fake-r2.test/{key}?X-Amz-Expires={expires_in}&X-Amz-Signature=fake"


def image_bytes(fmt : str = "PNG", size=(64, 64), *, exif=None, noise: bool = False) -> bytes:
    """A real image. 'noise=True' makes it large and hard to  compress"""
    if noise:
        image= Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        image= Image.new("RGB", size , (30,120,200))
    buffer= io.BytesIO()
    image.save(buffer, format=fmt, **({"exif": exif} if exif is not None else {}))
    return buffer.getvalue()
