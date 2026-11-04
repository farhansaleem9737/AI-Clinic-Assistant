"""Run the appointment and follow-up reminders, then the email outbox, once (D108, D109).

    cd backend
    python -m app.cli.run_reminders

The same run Cloud Scheduler triggers through POST /internal/reminders/run,
for development or another scheduler (e.g. a Cloud Run job). Safe to repeat:
nothing is created twice.
"""

import asyncio
import json
from dataclasses import asdict

from app.db.database import AsyncSessionLocal, engine
from app.services import email_outbox_service, reminder_service


async def _run() -> None:
    try:
        async with AsyncSessionLocal() as db:
            result = await reminder_service.run(db)
            emails = await email_outbox_service.run(db)
        print(json.dumps({**asdict(result), **{f"emails_{k}": v for k, v in asdict(emails).items()}}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
