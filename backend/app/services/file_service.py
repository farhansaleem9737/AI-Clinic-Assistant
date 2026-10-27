"""Storing files in R2 and keeping PostgreSQL in step with it.

The order of operations means the two can never disagree in a harmful way:

1. validate the bytes                       (file_validation, before this module)
2. upload the object under a new key        (upload)
3. insert/point the rows and commit         (commit_or_discard)
4. after the commit, delete what was replaced (finish_deletion)

If step 3 fails, the new object is deleted again. If a deletion fails, the
row stays ``pending_deletion`` and scripts/reconcile_storage.py retries it.
The worst case is an unreferenced object in R2, never a row pointing at
nothing.
"""


import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import StorageUnavailableError
from app.core.storage import Storage, StorageError
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.stored_file import FileCategory, FileStatus, StoredFile
from app.services.file_validation import CheckedFile

logger=logging.getLogger(__name__)

_KEY_PREFIX = {
    FileCategory.doctor_photo : "doctor-photos",
    FileCategory.patient_photo : "patient-photos",
    FileCategory.patient_document : "patient-documents",
}

def object_key(category: FileCategory, owner_id: uuid.UUID, file_id: uuid.UUID, extension: str) -> str:
    """Ids only: never a name, an MRN or the uploader's filename. The prefix
    lets R2 lifecycle and retention rules target one kind of file."""
    return f"{_KEY_PREFIX[category]}/{owner_id}/{file_id}.{extension}"

def photo_url(storage: Storage | None, photo: StoredFile | None) -> str | None:
    """A short-lived link for an <img> tag; None without a photo or storage."""
    return photo_url_for_key(storage, photo.object_key if photo is not None else None)


def photo_url_for_key(storage: Storage | None, object_key: str | None) -> str | None:
    """The same, when a query selected only the photo's object key."""
    if storage is None or object_key is None:
        return None
    return storage.presigned_get_url(object_key, expires_in=settings.photo_url_ttl_seconds)


async def upload(
        db: AsyncSession,
        storage: Storage,
        *,
        category: FileCategory,
        owner_id: uuid.UUID,
        checked: CheckedFile,
        uploaded_by: uuid.UUID,
        original_filename: str | None = None,
) -> StoredFile:
    """Put the object in R2 and add (not commit) its stored_files row."""
    file_id=uuid.uuid7()
    key= object_key(category, owner_id, file_id, checked.extension)
    try:
        await storage.put(key, checked.data, content_type=checked.content_type)
    except StorageError as exc:
        raise StorageUnavailableError("File storage is temporarily unavailable, please try again") from exc
    stored=StoredFile(
        id=file_id,
        bucket=storage.bucket,
        object_key=key,
        category=category,
        content_type=checked.content_type,
        size_bytes=len(checked.data),
        sha256=checked.sha256,
        original_filename=original_filename,
        uploaded_by_user_id=uploaded_by,
    )  
    db.add(stored)
    return stored


async def commit_or_discard(db: AsyncSession, storage: Storage, new_file: StoredFile) -> None:
    """Commit; if the database refuses, delete the object just uploaded."""
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await _delete_quietly(storage, new_file)
        raise


async def finish_deletion(db: AsyncSession, storage: Storage, file: StoredFile | None) -> None:
    """Delete the object of a file that a *committed* change already marked
    pending_deletion. A failure is logged and left to the reconcile script."""
    if file is None:
        return 
    if await _delete_quietly(storage, file):
        file.status = FileStatus.deleted
        await db.commit()

async def replace_photo(
    db: AsyncSession,
    storage: Storage,
    owner: Doctor | Patient,
    *,
    category: FileCategory,
    checked: CheckedFile,
    uploaded_by: uuid.UUID,
) -> None:
    """Give a doctor or patient a new photo, then delete the old one."""
    old= owner.photo
    new= await upload(db, storage, category=category, owner_id=owner.id, checked=checked, uploaded_by=uploaded_by)
    owner.photo  = new
    if old is not None:
        old.status = FileStatus.pending_deletion
    await commit_or_discard(db, storage, new)
    await finish_deletion(db, storage, old)

async def remove_photo(db: AsyncSession, storage: Storage, owner: Doctor | Patient) -> None:
    old=owner.photo
    if old is None:
        return
    owner.photo=None
    old.status=FileStatus.pending_deletion
    await db.commit()
    await finish_deletion(db, storage, old)

async def _delete_quietly(storage: Storage, file: StoredFile) -> bool:
    try:
        await storage.delete(file.object_key)
    except StorageError:
        logger.warning("storage_deleted_deferred", extra={"file_id": str(file.id)})
        return False
    return True