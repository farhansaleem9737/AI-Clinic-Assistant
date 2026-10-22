"""Reading uploaded files (multipart/form-data) with a size limit."""

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import FileTooLargeError, UnsupportedFileError
from app.services.file_validation import CheckedFile, check_document, prepare_photo

_CHUNK = 1024*1024

async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """The file's bytes, refusing it as soon as it is larger than ``max_bytes``.

    Starlette has already received the request body by the time an endpoint
    runs; this limit protects memory and R2. The reverse proxy (Nginx
    client_max_body_size) limits what is received at all.
    """
    too_large=FileTooLargeError(
        f"the file is larger than {max_bytes // (1024 * 1024)} MB", details={"max_bytes":max_bytes}
    )
    if file.size is not None and file.size > max_bytes:
        raise too_large
    data=bytearray()
    while chunk:=await file.read(_CHUNK):
        data += chunk
        if len(data) > max_bytes:
            raise too_large
    if not data:
        raise UnsupportedFileError("The file is empty", code="EMPTY_FILE")
    return bytes(data)

async def read_photo(file:UploadFile) -> CheckedFile:
    data= await read_upload(file, settings.max_photo_bytes)
    # Decoding and re_encoding an image in CPU work: keep it off the event loop.
    return await run_in_threadpool(prepare_photo, data)

async def read_document(file: UploadFile) -> CheckedFile:
    data= await read_upload(file, settings.max_document_bytes)
    return await run_in_threadpool(check_document, data)