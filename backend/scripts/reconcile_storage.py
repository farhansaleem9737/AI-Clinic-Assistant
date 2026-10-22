"""Retry deleting R2 objects whose rows are stuck in pending_deletion.

A failed delete never breaks a request (file_service logs it and moves on);
this finishes the job later. Safe to run repeatedly: deleting a missing key
succeeds. Run from backend/:  python -m scripts.reconcile_storage
"""

import asyncio
from sqlalchemy import select

from app.core.storage import close_storage, get_storage
from app.db.database import AsyncSessionLocal, engine
from app.models.stored_file import StoredFile, FileStatus
from app.services.file_service import finish_deletion

async def main() -> None:
    storage = get_storage()
    deleted= 0
    async with AsyncSessionLocal() as db:
        pending = (await db.scalars(select(StoredFile).where(StoredFile.status == FileStatus.pending_deletion))).all()
        for file in pending:
            await finish_deletion(db, storage, file)
            deleted += file.status is FileStatus.deleted
    print(f"pending: {len(pending)}, deleted now: {deleted}")
    await engine.dispose()
    close_storage()


if __name__=="__main__":
    asyncio.run(main())