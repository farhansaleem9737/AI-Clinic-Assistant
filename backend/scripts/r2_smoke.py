"""One-off connectivity check against the bucket in backend/.env. Prints
statuses only, never a URL or a key. Run from backend/:  python -m scripts.r2_smoke"""

import asyncio
import urllib.request
import uuid

from app.core.storage import close_storage, get_storage


async def main() -> None:
    storage = get_storage()
    key = f"smoke/{uuid.uuid4()}.txt"
    await storage.put(key, b"hello from clinic", content_type="text/plain")
    print("put: ok")
    info = await storage.head(key)
    print("head:", "ok" if info and info.size == 17 else info)
    with urllib.request.urlopen(storage.presigned_get_url(key, expires_in=60), timeout=10) as response:
        print("presigned get:", response.status)
    await storage.delete(key)
    print("delete:", "ok" if await storage.head(key) is None else "object still there")
    close_storage()


if __name__ == "__main__":
    asyncio.run(main())
