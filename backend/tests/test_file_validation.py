import io

import pytest
from PIL import Image

from app.core.exceptions import UnsupportedFileError
from app.services.file_validation import check_document, detect_type, display_filename, prepare_photo
from tests.fakes import PDF_BYTES, image_bytes

SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (image_bytes("JPEG"), "image/jpeg"),
        (image_bytes("PNG"), "image/png"),
        (image_bytes("WEBP"), "image/webp"),
        (PDF_BYTES, "application/pdf"),
        (SVG, None),
        (b"MZ\x90\x00", None),
    ],
)
def test_type_comes_from_the_bytes(data, expected):
    assert detect_type(data) == expected


def test_photo_is_shrunk_reencoded_and_stripped():
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # camera make: stands in for any metadata, e.g. GPS
    checked = prepare_photo(image_bytes("JPEG", (2000, 1000), exif=exif))
    assert (checked.content_type, checked.extension) == ("image/webp", "webp")
    assert b"SecretCam" not in checked.data
    with Image.open(io.BytesIO(checked.data)) as image:
        assert image.format == "WEBP" and max(image.size) == 512


@pytest.mark.parametrize("data", [SVG, b"MZ\x90\x00 not an image", b"\xff\xd8\xff" + b"0" * 200, PDF_BYTES])
def test_photo_rejects_anything_but_real_images(data):
    with pytest.raises(UnsupportedFileError):
        prepare_photo(data)


def test_documents_accept_pdf_and_scans_unchanged():
    assert check_document(PDF_BYTES).data == PDF_BYTES
    assert check_document(PDF_BYTES).content_type == "application/pdf"
    assert check_document(image_bytes("PNG")).extension == "png"


@pytest.mark.parametrize(
    "data", [PDF_BYTES[:-7], image_bytes("WEBP"), b"<html></html>", b"\x89PNG\r\n\x1a\n" + b"0" * 50]
)
def test_documents_reject_other_content(data):
    with pytest.raises(UnsupportedFileError):
        check_document(data)


def test_display_filename_drops_paths_and_control_characters():
    assert display_filename("C:\\Users\\x\\report\x00.pdf") == "report.pdf"
    assert display_filename("") is None
