"""Set a new password for an administrator who cannot sign in (D87).

    cd backend
    python -m app.cli.reset_admin_password --email admin@example.com

Run by hand by someone with access to the server and its database settings.
Only administrator accounts can be reset here; patients, doctors and staff
are not. The password is read from a prompt (never an argument, so it stays
out of shell history), every session of the account ends, and the reset is
written to the audit log. There is no HTTP equivalent.
"""

import argparse
import asyncio
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.engine import make_url

from app.cli.create_admin import _fail, _read_password
from app.core.config import settings
from app.core.exceptions import DomainError
from app.db.database import AsyncSessionLocal, engine
from app.schemas.common import LoginEmail
from app.services import admin_service


async def _reset(email: str, password: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await admin_service.reset_admin_password(db, email=email, password=password)
    except DomainError as exc:
        _fail(exc.message)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.reset_admin_password", description="Set a new password for an administrator."
    )
    parser.add_argument("--email", help="email address of the administrator account")
    args = parser.parse_args(argv)
    try:
        email = TypeAdapter(LoginEmail).validate_python(args.email or input("Email: "))
    except ValidationError as exc:
        _fail(exc.errors()[0]["msg"])

    url = make_url(settings.database_url)
    print(f"Database: {url.database} on {url.host} ({settings.environment})")
    print(f"Setting a new password for administrator {email}")
    password = _read_password()
    if input("Type RESET to continue: ").strip() != "RESET":
        _fail("cancelled; nothing was changed")

    asyncio.run(_reset(email, password))
    print(f"Password changed. Sign in at {settings.frontend_base_url}/login")


if __name__ == "__main__":
    main()
