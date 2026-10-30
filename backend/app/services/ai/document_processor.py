"""Validate assistant uploads and extract their text (D96).

The type is decided from the bytes, never from the client's filename or
Content-Type (plain text is the one exception: it has no signature, so the
.txt name is required *and* the bytes must decode as text). Nothing is
executed or rendered; DOCX is unzipped and only its document XML is read,
with size limits and no DTDs. Extraction is CPU-bound: call through a
thread pool.
"""

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import UnsupportedFileError
from app.services.file_validation import detect_type

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT = "text/plain"
EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", DOCX: "docx", TEXT: "txt"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

MAX_TEXT_CHARS = 120_000
MAX_PDF_PAGES = 300
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# A PDF with less readable text than this is treated as scanned (image-only).
MIN_TEXT_CHARS = 20


@dataclass(frozen=True)
class Extracted:
    content_type: str
    extension: str
    status: str  # ready | no_text | failed
    text: str | None
    page_count: int | None
    note: str | None = None


def clean_filename(name: str | None) -> str:
    """Display name only: last path segment, normalised, no control characters."""
    name = (name or "document").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip(" .")
    return (name or "document")[:255]


def detect(data: bytes, filename: str) -> str:
    """The real type of an upload, or UnsupportedFileError."""
    if not data:
        raise UnsupportedFileError("The file is empty", code="EMPTY_FILE")
    kind = detect_type(data)
    if kind in EXTENSIONS:
        return kind
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return DOCX
        except zipfile.BadZipFile:
            pass
        raise UnsupportedFileError("Only Word .docx files are accepted from ZIP-based formats")
    if filename.lower().endswith(".txt") and b"\x00" not in data[:65536]:
        try:
            data.decode("utf-8-sig")
            return TEXT
        except UnicodeDecodeError:
            pass
    raise UnsupportedFileError("Accepted files: PDF, PNG, JPG, WEBP, DOCX and TXT")


def _squeeze(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _pdf(data: bytes) -> Extracted:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return Extracted("application/pdf", "pdf", "failed", None, None, "The PDF is password-protected.")
        pages = reader.pages
        count = len(pages)
        chunks, total = [], 0
        for number, page in enumerate(pages[:MAX_PDF_PAGES], start=1):
            text = _squeeze(page.extract_text() or "")
            if text:
                chunk = f"[Page {number}]\n{text}"
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_TEXT_CHARS:
                    break
    except (PdfReadError, ValueError, KeyError, TypeError, OSError):
        return Extracted("application/pdf", "pdf", "failed", None, None, "The PDF could not be read.")
    text = "\n\n".join(chunks)[:MAX_TEXT_CHARS]
    if len(text) < MIN_TEXT_CHARS:
        return Extracted("application/pdf", "pdf", "no_text", None, count, "No selectable text: probably a scanned PDF.")
    return Extracted("application/pdf", "pdf", "ready", text, count)


def _docx(data: bytes) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                return Extracted(DOCX, "docx", "failed", None, None, "The document is too large to read.")
            xml = archive.read(info)
        if b"<!DOCTYPE" in xml[:2048]:
            return Extracted(DOCX, "docx", "failed", None, None, "The document could not be read.")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError):
        return Extracted(DOCX, "docx", "failed", None, None, "The document could not be read.")
    paragraphs = ["".join(node.text or "" for node in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
    text = _squeeze("\n".join(paragraphs))[:MAX_TEXT_CHARS]
    if not text:
        return Extracted(DOCX, "docx", "no_text", None, None, "The document has no text.")
    return Extracted(DOCX, "docx", "ready", text, None)


def extract(data: bytes, filename: str) -> Extracted:
    """Detect and extract. Raises UnsupportedFileError for files not accepted at all."""
    kind = detect(data, filename)
    if kind == "application/pdf":
        return _pdf(data)
    if kind == DOCX:
        return _docx(data)
    if kind == TEXT:
        text = _squeeze(data.decode("utf-8-sig"))[:MAX_TEXT_CHARS]
        return Extracted(TEXT, "txt", "ready" if text else "no_text", text or None, None)
    # Images: stored as they are; only a vision-capable model can read them.
    return Extracted(kind, EXTENSIONS[kind], "no_text", None, None, "An image: readable only by a vision-capable model.")
