"""Check the email setup without emailing anyone (D124).

    cd backend
    python -m app.cli.email_check                  # SMTP: connect, TLS, log in, hang up; Brevo: check the key. Sends nothing
    python -m app.cli.email_check --status         # also: emails in the outbox per status
    python -m app.cli.email_check --send-test you@example.com
                                                   # one test message to an address you type

Prints the backend, host, port and security mode, never the username,
password or API key. --send-test goes only to the address given on the command line,
never to an account from the database, and contains no clinic data.
"""

import argparse
import asyncio
import json
import sys

from app.core.config import settings
from app.services import email_service


async def _status() -> dict[str, int]:
    from app.db.database import AsyncSessionLocal, engine
    from app.services import email_outbox_service

    try:
        async with AsyncSessionLocal() as db:
            return await email_outbox_service.status_counts(db)
    finally:
        await engine.dispose()


async def _main(args: argparse.Namespace) -> int:
    backend = settings.effective_email_backend
    report = {"backend": backend.value}
    if backend.value == "smtp":
        report |= {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "security": "implicit TLS" if settings.smtp_ssl else "STARTTLS" if settings.smtp_starttls else "none (local only)",
            "login": bool(settings.smtp_username),
        }
    elif backend.value == "brevo":
        report["api"] = email_service.BREVO_API + " (HTTPS)"
    report |= {"from": settings.email_from, "links_to": settings.frontend_base_url}
    code = 0
    try:
        await email_service.check_connection()
        report["connection"] = "ok"
    except ValueError as exc:
        report["connection"] = str(exc)
        code = 1
    except email_service.DeliveryError as exc:
        report["connection"] = f"failed: {exc.reason}"
        code = 1
    if args.send_test and code == 0:
        email = email_service.Email(
            to=args.send_test,
            subject="Test email — Clinic AI Assistant",
            text="This is a test of the Clinic AI Assistant email settings. No action is needed.\n",
        )
        try:
            await email_service.deliver(email)
            report["test_email"] = "accepted by the SMTP server"
        except email_service.DeliveryError as exc:
            report["test_email"] = f"failed: {exc.reason}"
            code = 1
    if args.status:
        report["outbox"] = await _status()
    print(json.dumps(report, indent=2))
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="show emails in the outbox per status")
    parser.add_argument("--send-test", metavar="ADDRESS", help="send one test message to this address only")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
