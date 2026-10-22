"""Decide what an uploaded file really is, from its bytes.

The browser's Content-Type and the filename extension are chosen by the
client, so both are ignored. The first bytes ("magic numbers") decide the
type, and images are actually decoded to prove they are images. SVG and
HTML are never accepted: they can carry scripts.
"""

import hashlib
import io
import unicodedata
from dataclasses import dataclass
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import UnsupportedFileError

# Decompression-bomb guard: refuse images that decode to more pixels than this
Image.MAX_IMAGE_PIXELS=40_000_000

PHOTO_MAX_SIDE = 512

PHOTO_TYPE = {"image/jpeg", "image/png", "image/webp"}
# Detected type -> extension used in the object key.
DOCUMENT_TYPES={"application/pdf":"pdf", "image/jpeg": "jpg", "image/png":"png"}
_IMAGE_ERRORS=(UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError)


@dataclass(frozen=True)
class CheckedFile:
    """Bytes that passed validation, with the type we detected ourselves."""
    data: bytes
    content_type: str
    extension: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def detect_type(data : bytes) -> str | None:
    if  data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if  data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if  data[:4]== b"RIFF" and data[8:12] == b"WEBP" :
        return "image/webp"
    if  data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def prepare_photo(data : bytes) -> CheckedFile:
    """Validate a profile photo and re-encode it as a small WebP.

    Re-encoding proves the file is a real image and drops EXIF metadata
    (camera, GPS location) and anything appended after the image data.
    CPU-bound: call it through run_in_threadpool.
    """
    if detect_type(data) not in PHOTO_TYPE:
        raise UnsupportedFileError("Profile photo must be jpeg, png or webp immages")
    try:
        with Image.open(io.BytesIO(data)) as source:
            # phone store "rotate me" in EXIF: apply it before EXIF is dropped.
            image = ImageOps.exif_transpose(source).convert("RGB")
    except _IMAGE_ERRORS as exc:
        raise UnsupportedFileError("the image could not be read") from exc
    image.thumbnail((PHOTO_MAX_SIDE,PHOTO_MAX_SIDE))
    output=io.BytesIO()
    image.save(output, format="WEBP", quality=85)
    return CheckedFile(output.getvalue(), "image/webp", "webp")


def check_document(data: bytes) -> CheckedFile:
    """Accept PDFs and scanned JPEG/PNG pages, stored unchanged (no re-encoding,
    so clinical images keep their quality). CPU-bound for large images."""

    content_type=detect_type(data)
    if content_type not in DOCUMENT_TYPES:
        raise UnsupportedFileError("Document must be PDF, JPEG, or PNG files")
    if content_type == "application/pdf":
        # A complete PDF ends with the %%EOF, sometime followed by whitespace.
        if b"%%EOF" not in data[-2048:]:
            raise UnsupportedFileError("The PDF file is incomplete or damaged")
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except _IMAGE_ERRORS as exc:
            raise UnsupportedFileError("The image could not be read") from exc
    return CheckedFile(data, content_type, DOCUMENT_TYPES[content_type])


def display_filename(name: str | None) -> str | None:
    """The uploader's filename, made safe to store and show. Never part of a key."""
    if not name:
        return None
    name = name.replace("\\","/").rsplit("/",1)[-1]
    name="".join(ch for ch in unicodedata.normalize("NFC", name) if unicodedata.category(ch)[0] != "C")
    return name.strip()[:255] or None