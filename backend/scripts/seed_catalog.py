"""Load the reference medical catalog (D118): 24 broad departments, their
specializations, and the conditions and symptoms that route to them.

    cd backend
    python -m scripts.seed_catalog           # apply
    python -m scripts.seed_catalog --dry-run # show what would change, change nothing

Idempotent: run it any number of times. It never deletes, renames or merges
an existing department, specialization or doctor. An existing department named
like a catalog entry ("General Medicine") becomes that entry and keeps its
name. Doctors are linked to a specialization only when the specialization on
their approved profile is exactly that specialization's name or alias.
"""

import asyncio
import sys

from app.db.database import AsyncSessionLocal, engine
from app.services import catalog_service


async def main(dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        report = await catalog_service.seed(db, commit=not dry_run)
        if dry_run:
            await db.rollback()
    await engine.dispose()
    print("DRY RUN: nothing was saved.\n" if dry_run else "Catalog loaded.\n")
    print(f"Departments created ({len(report.departments_created)}): {', '.join(report.departments_created) or '-'}")
    print(f"Existing departments matched ({len(report.departments_matched)}): {', '.join(report.departments_matched) or '-'}")
    print(f"Specializations created: {report.specializations_created}")
    print(f"Department-specialization links created: {report.department_links_created}")
    print(f"Conditions/symptoms created: {report.topics_created} (links: {report.topic_links_created})")
    print(f"Doctor-specialization links created: {len(report.doctor_links_created)}")
    for text, name in report.doctor_links_created:
        print(f"  {text!r} -> {name}")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
