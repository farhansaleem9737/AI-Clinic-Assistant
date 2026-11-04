# Email (D87, D109)

## What sends email

| Event | Recipient | How |
|---|---|---|
| Administrator invitation | the invited address | sent at once; the admin sees the result |
| Appointment booked (online or by staff) | the patient's account | outbox |
| Confirmed by the clinic | the patient | outbox |
| Rescheduled | the patient | outbox |
| Cancelled | the patient | outbox |
| Appointment reminder, 24 h before | the patient | outbox |
| Follow-up due | the patient | outbox |
| Doctor application approved / not approved | the applicant | outbox |

**Doctors and staff:** they get the in-app notifications only (docs/NOTIFICATIONS.md).
They don't get emails.

**What an email contains:** when, the doctor, the department and a link into the app.
- It never includes the reason for the visit, notes, documents, diagnoses or
  reviewer notes.
- Every email has a plain-text and an HTML version.

**Preferences:** an email is sent only if two switches are on, in the bell's
settings view:
- **its category:** appointment updates, reminders or follow-ups;
- **"Also by email".**

Application decisions are always sent, because they answer the user's own
application.

### Why invitations are sent at once

An invitation link carries a one-time credential. The database stores only its
hash. Queueing the email would mean storing the raw token, so invitations keep
being sent during the request, and the admin sees whether that worked.

## How it is delivered

```
event ─ same transaction ─▶ email_outbox (pending)
         after commit ─▶ this process starts sending at once   (best effort)
Cloud Scheduler ─▶ POST /internal/reminders/run ─▶ reminders, then the outbox   (every 15 min)
outbox run: claim due rows with FOR UPDATE SKIP LOCKED → commit → SMTP (no transaction open) → record
```

- **Bookings never wait for SMTP:** a booking never waits for an SMTP server, and
  is never undone because email failed.
- **Retries:** a temporary failure is retried after 1, 5, 15, 60 and 180 minutes,
  `EMAIL_MAX_ATTEMPTS` times in all (default 6), then marked `failed`. Temporary
  failures include:
  - network errors and timeouts;
  - TLS problems;
  - 4xx replies;
  - wrong credentials.
- **Permanent failures:** a 5xx refusal of the address fails at once.
- **Statuses:**
  - `sent` means the SMTP server accepted the message;
  - `written` means a development file;
  - `expired` means it was too late (for example, a reminder after the start).
- **Concurrency:** a claim is a 10-minute lease, so runs on several Cloud Run
  instances never take the same row. Delivery is at least once, not exactly once:
  if a run dies after the server accepted a message but before recording it, that
  message can be sent again once the lease ends.
- **Duplicates:** one email per event and user is enforced by a unique key.
- **Privacy after sending:** the body is cleared once sent; the subject, status
  and timestamps stay.
- **Error records:** `last_error` holds an error class and SMTP code only, never
  server text, addresses or passwords.

## Settings

| Variable | Production value | Notes |
|---|---|---|
| `EMAIL_BACKEND` | `smtp` | unset: `outbox` in development (files in `backend/var/outbox`), otherwise `smtp` if `SMTP_HOST` is set, else `none` |
| `EMAIL_FROM` | `Clinic AI Assistant <no-reply@yourclinic.com>` | must be a verified sender at the provider |
| `SMTP_HOST` | provider's host | |
| `SMTP_PORT` | `587` (or `465`) | **not 25**: Google Cloud blocks outbound port 25 |
| `SMTP_STARTTLS` | `true` for 587 | |
| `SMTP_SSL` | `true` for 465 (and `SMTP_STARTTLS=false`) | |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | provider credentials | **secret**: Secret Manager |
| `SMTP_TIMEOUT_SECONDS` | `10` | |
| `FRONTEND_BASE_URL` | `https://your-app.vercel.app` | used in every link |
| `EMAIL_REMINDER_OFFSETS_MINUTES` | `1440` | must be among `REMINDER_OFFSETS_MINUTES` |
| `EMAIL_MAX_ATTEMPTS` | `6` | |
| `EMAIL_SEND_AFTER_COMMIT` | `true` | false: only the scheduled run sends |

**Refused at start-up:**
- SMTP without TLS. The only exception is a local test server with
  `SMTP_ALLOW_PLAINTEXT_LOCALHOST=true`.
- STARTTLS and implicit TLS together, or STARTTLS on port 465.
- A username without a password.
- A malformed `EMAIL_FROM`.

A server that doesn't offer STARTTLS fails the send; it never falls back to
plaintext.

**Without SMTP settings:** outside development, nothing is queued and nothing is
reported as sent. The reminder run reports zero emails.

## Development

- **No real email:** the default `outbox` backend writes `.eml` files to
  `backend/var/outbox`.
- **To see real rendering:** run a local test server such as Mailpit:
  - Docker: `docker run -p 1025:1025 -p 8025:8025 axllent/mailpit`.
  - Settings: `EMAIL_BACKEND=smtp`, `SMTP_HOST=localhost`, `SMTP_PORT=1025`,
    `SMTP_STARTTLS=false`, `SMTP_ALLOW_PLAINTEXT_LOCALHOST=true`.
- **Sending the queue by hand:** `python -m app.cli.run_reminders`.

## Production setup (not done yet)

1. **Provider:** use one that offers SMTP on 587/465 with an API key, such as
   SendGrid, Mailgun, Postmark, Amazon SES or Brevo.
   - Verify the sending domain. This usually means adding the provider's SPF and
     DKIM DNS records, plus a DMARC record.
   - Use an address on that domain for `EMAIL_FROM`.
   - Note the provider's sending quota and rate limit. The outbox sends at most 25
     emails per pass and spreads retries out.
2. **Secrets:**
   ```bash
   printf '%s' 'THE_SMTP_PASSWORD' | gcloud secrets create smtp-password --data-file=- --project=$PROJECT
   gcloud secrets add-iam-policy-binding smtp-password --project=$PROJECT \
     --member="serviceAccount:YOUR_RUN_SERVICE_ACCOUNT" --role="roles/secretmanager.secretAccessor"
   ```
3. **Cloud Run:**
   ```bash
   gcloud run services update YOUR_SERVICE --region=asia-southeast1 --project=$PROJECT \
     --update-secrets=SMTP_PASSWORD=smtp-password:latest \
     --update-env-vars="EMAIL_BACKEND=smtp,SMTP_HOST=smtp.provider.com,SMTP_PORT=587,SMTP_STARTTLS=true,SMTP_USERNAME=apikey,EMAIL_FROM=Clinic AI Assistant <no-reply@yourclinic.com>,FRONTEND_BASE_URL=https://your-app.vercel.app"
   ```
   - Outbound connections to the provider's port 587/465 work from Cloud Run
     without extra setup.
   - With a VPC connector and "all traffic" egress, the VPC must allow it too.
4. **Scheduling:** the reminder job in docs/NOTIFICATIONS.md also runs the outbox,
   so no second job is needed. The after-commit start usually sends within seconds.
   With request-based CPU, Cloud Run may slow that work after the response; the
   scheduled run is the safety net.
5. **Monitoring:**
   - In Cloud Logging, watch `email_delivery_failed` (with `error` and `final`)
     and `email_outbox_run` (counts).
   - Alert on `final=true`.
   - Rows with status `failed` are kept for review, with no body.
6. **A controlled end-to-end test, before telling users:**
   - Book an appointment for a test patient whose email is yours.
   - Check that it arrives.
   - Check its SPF/DKIM pass in the message headers.
