"""Create the first administrator (D87).

    cd backend
    python -m app.cli.create_admin --email you@clinic.example --name "Your Name"

Run it once, by hand, against a database that has no administrator. It asks
for the password twice without echoing it, creates a *new* account and grants
it the admin role in one transaction. It refuses when:

* an administrator already exists (invite further administrators from
  Admin > Users > Invite Administrator), or
* the email already belongs to an account (it never promotes an existing
  patient, doctor or staff account).

Concurrent runs are serialized by a database lock, so two operators cannot
both create a "first" administrator. There is no HTTP equivalent.
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.exceptions import DomainError
from app.db.database import AsyncSessionLocal, engine
from app.schemas.admin import Name
from app.schemas.common import LoginEmail
from app.services import admin_service

MIN_PASSWORD = 8
MAX_PASSWORD = 128


def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _read_password() -> str:
    if not sys.stdin.isatty():
        _fail("run this in an interactive terminal: the password is only read from a prompt")
    password = getpass.getpass("Password (not shown): ")
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        _fail(f"the password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters")
    if getpass.getpass("Repeat the password: ") != password:
        _fail("the passwords do not match")
    return password


async def _create(name: str, email: str, password: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await admin_service.bootstrap_first_admin(db, name=name, email=email, password=password)
    except DomainError as exc:
        _fail(exc.message)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli.create_admin", description="Create the first administrator.")
    parser.add_argument("--email", help="email address of the new administrator account")
    parser.add_argument("--name", help="full name")
    args = parser.parse_args(argv)

    try:
        email = TypeAdapter(LoginEmail).validate_python(args.email or input("Email: "))
        name = TypeAdapter(Name).validate_python(args.name or input("Full name: "))
    except ValidationError as exc:
        _fail(exc.errors()[0]["msg"])

    # Which database, without credentials: host and database name only.
    url = make_url(settings.database_url)
    print(f"Database: {url.database} on {url.host} ({settings.environment})")
    print(f"Creating administrator {email}")
    password = _read_password()
    if input("Type CREATE to continue: ").strip() != "CREATE":
        _fail("cancelled; nothing was changed")

    asyncio.run(_create(name, email, password))
    print(f"Administrator {email} created. Sign in at {settings.frontend_base_url}/login")


if __name__ == "__main__":
    main()
