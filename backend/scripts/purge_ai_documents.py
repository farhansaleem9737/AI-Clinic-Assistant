"""Delete assistant documents older than AI_DOCUMENT_RETENTION_DAYS (D96)
and conversations untouched for AI_CONVERSATION_RETENTION_DAYS (D100).

    cd backend
    python -m scripts.purge_ai_documents            # report only
    python -m scripts.purge_ai_documents --delete   # delete files and rows

Run it on a schedule (e.g. daily). A retention of 0 keeps those records
until their owner deletes them. Usage records (counts only) are kept.
Prints counts only, never names or contents.
"""

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.core.storage import StorageError, get_optional_storage
from app.db.database import AsyncSessionLocal, engine
from app.models.ai import AiConversation, AiDocument


async def purge_conversations(delete: bool) -> None:
    days = settings.ai_conversation_retention_days
    if days <= 0:
        print("AI_CONVERSATION_RETENTION_DAYS is 0: no conversations are purged.")
        return
    cutoff = clock.utcnow() - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        old = (await db.scalars(select(AiConversation).where(AiConversation.updated_at < cutoff))).all()
        print(f"{len(old)} conversation(s) untouched for more than {days} days.")
        if not delete or not old:
            return
        # Messages go with them (ON DELETE CASCADE); their documents are handled below.
        for conversation in old:
            await db.delete(conversation)
        await db.commit()
        print(f"Deleted {len(old)} conversation(s).")


async def purge(delete: bool) -> None:
    await purge_conversations(delete)
    days = settings.ai_document_retention_days
    if days <= 0:
        print("AI_DOCUMENT_RETENTION_DAYS is 0: nothing is purged.")
        return
    cutoff = clock.utcnow() - timedelta(days=days)
    storage = get_optional_storage()
    async with AsyncSessionLocal() as db:
        old = (await db.scalars(select(AiDocument).where(AiDocument.created_at < cutoff))).all()
        print(f"{len(old)} document(s) older than {days} days.")
        if not delete or not old:
            return
        if storage is None:
            print("Storage is not configured; refusing to delete rows whose files would be left behind.")
            return
        removed = 0
        for document in old:
            try:
                await storage.delete(document.object_key)
            except StorageError:
                continue
            await db.delete(document)
            removed += 1
        await db.commit()
        print(f"Deleted {removed} document(s).")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="actually delete (default: report only)")
    asyncio.run(purge(parser.parse_args().delete))
