# Email (D87, D109, D124, D125)

## What sends email

| Event | Recipient | How |
|---|---|---|
| Administrator invitation | the invited address | sent at once; the admin sees the result |
| Registration verification code (6 digits, 10 min, 5 tries) | the address being registered | sent at once; the form shows if it failed |
| Appointment booked (online or by staff) | the patient's account; the doctor's, unless the doctor booked it (D124) | outbox |
| Confirmed by the clinic | the patient | outbox |
| Rescheduled | the patient; the doctor (both doctors if it moved to another: the previous one gets a cancellation), unless they did it | outbox |
| Cancelled | the patient; the doctor, unless they did it | outbox |
| Appointment reminder, 24 h and 1 h before | the patient | outbox |
| Follow-up due | the patient | outbox |
| Doctor application approved / not approved | the applicant | outbox |
| New doctor application waiting for review | everyone who may review applications (admins) | outbox |

**Front desk:** in-app notifications only (docs/NOTIFICATIONS.md); every online
booking by email would be noise for a shared desk.

**What an email contains:** the doctor, the date, the time with the clinic's
time zone (e.g. `14:30 (Asia/Karachi)`), the department, the appointment's
status as stored (a `requested` booking is never called confirmed), and a
"View appointment" button.
- It never includes the reason for the visit, notes, documents, diagnoses,
  AI output or reviewer notes. A doctor's email doesn't name the patient; the
  app does, after sign-in.
- Every email has a plain-text and an HTML version.

**The View appointment link** is `FRONTEND_BASE_URL/appointments/<id>`, the app's
own detail page. It carries no token. Signed out, the app asks for sign-in and
then returns to that page; the API shows the appointment only to its patient,
its doctor and staff, so changing the id in the address shows nothing else.
In production `FRONTEND_BASE_URL` must be the public `https://` address: the
backend refuses to start with `http://` or localhost.

**Cancelled or moved before the email went out:** that appointment's unsent
"booked", "confirmed" and reminder emails are withdrawn (status `expired`), so
nobody is told a cancelled visit is booked. One already being sent may still
arrive (at least once).
- Every email has a plain-text and an HTML version.

**Preferences:** an email is sent only if two switches are on, in the bell's
settings view:
- **its category:** appointment updates, reminders or follow-ups;
- **"Also by email".**

Application decisions, and new applications to reviewers, depend on
"Also by email" only.

### Why invitations are sent at once

An invitation link carries a one-time credential. The database stores only its
hash. Queueing the email would mean storing the raw token, so invitations keep
being sent during the request, and the admin sees whether that worked.

## How it is delivered

```
event ─ same transaction ─▶ email_outbox (pending)
         after commit ─▶ this process starts sending at once   (best effort)
         a temporary failure ─▶ this process wakes up when the retry is due (D124, best effort)
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
- **Error records:** `last_error` holds an error class and SMTP code (or, for
  network errors, the error number: `gaierror 11001` = the host name did not
  resolve) only, never server text, addresses or passwords.
- **Retries without a scheduler:** after a temporary failure the process sets a
  wake-up for the retry time (up to 6 h ahead), so a short outage heals on a
  single always-on instance. It is lost on restart or scale-to-zero: the
  scheduled run remains the guarantee.

## Settings

| Variable | Production value | Notes |
|---|---|---|
| `EMAIL_BACKEND` | `brevo` on Render free, else `smtp` or `brevo` | unset: `outbox` in development (files in `backend/var/outbox`), otherwise `brevo` if `BREVO_API_KEY` is set, `smtp` if `SMTP_HOST` is set, else `none` |
| `BREVO_API_KEY` | Brevo API key (not its SMTP key) | **secret**; for `EMAIL_BACKEND=brevo`, sent over HTTPS only |
| `EMAIL_FROM` | `Clinic AI Assistant <no-reply@yourclinic.com>` | must be a verified sender at the provider |
| `SMTP_HOST` | provider's host | |
| `SMTP_PORT` | `587` (or `465`) | **not 25**: Google Cloud blocks outbound port 25 |
| `SMTP_STARTTLS` | `true` for 587 | |
| `SMTP_SSL` | `true` for 465 (and `SMTP_STARTTLS=false`) | |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | provider credentials | **secret**: Secret Manager |
| `SMTP_TIMEOUT_SECONDS` | `10` | |
| `FRONTEND_BASE_URL` | `https://your-app.vercel.app` | used in every link |
| `EMAIL_REMINDER_OFFSETS_MINUTES` | `1440,60` | must be among `REMINDER_OFFSETS_MINUTES` |
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
- **Checking the SMTP settings:** `python -m app.cli.email_check` connects, starts
  TLS, logs in and hangs up: it sends nothing. `--status` adds the outbox counts
  per status; `--send-test you@example.com` sends one plain test message to
  that address only (never to an account from the database).

## Hosts that block SMTP: Brevo over HTTPS (D125)

Render's free plan (and some other hosts) block outbound connections to SMTP
ports 25, 465 and 587. Every SMTP send from there fails with a network error
(`OSError`), and so do registration codes. `EMAIL_BACKEND=brevo` posts the same
message to Brevo's API over HTTPS (port 443) instead. Everything else stays the
same: the outbox, retries, templates and preferences.

1. Create a free Brevo account at brevo.com (300 emails a day).
2. **Senders, Domains & Dedicated IPs → Senders → Add a sender**: the address you
   send from (e.g. your Gmail), then confirm the email Brevo sends to it. A
   domain of your own with Brevo's DKIM/DMARC records lands in inboxes more
   reliably than a Gmail sender.
3. **SMTP & API → API keys → Generate a new API key.** Copy it once.
4. On Render, under Environment: `EMAIL_BACKEND=brevo`, `BREVO_API_KEY=<the key>`,
   `EMAIL_FROM=Clinic AI Assistant <the verified sender>`, `FRONTEND_BASE_URL=https://<vercel app>`.
5. Check it: Render → Shell (or locally with the same variables)
   `python -m app.cli.email_check --status --send-test you@example.com`.

Errors are kept as the HTTP status and Brevo's code, e.g. `Brevo 401 unauthorized`
(wrong key) or `Brevo 400 invalid_parameter` (a bad address, which isn't retried).
They never include Brevo's message text or the key.

## Production setup (not done yet)

The local `.env` currently uses Gmail SMTP with an app password. That's fine
for testing, but a Gmail account allows about 500 recipients a day and its
messages come from a personal address. For production, use a transactional
provider with your own domain:

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
   - `python -m app.cli.email_check --status` (from a machine with the
     production settings) shows the outbox per status: `failed` above zero, or
     `pending` that keeps growing, needs a look.
   - In the logs, watch `email_delivery_failed` (with `error` and `final`)
     and `email_outbox_run` (counts).
   - Alert on `final=true`.
   - Rows with status `failed` are kept for review, with no body.
6. **A controlled end-to-end test, before telling users:**
   - Book an appointment for a test patient whose email is yours.
   - Check that it arrives.
   - Check its SPF/DKIM pass in the message headers.
   - Open its "View appointment" button signed out: the app asks for sign-in,
     then shows that appointment. Signed in as another patient, the same link
     shows nothing.
   - The doctor's copy arrives at the doctor's address.

### Other hosts than Cloud Run

Any container host works. It needs:
- outbound TCP to the SMTP port, 587 or 465 (some hosts block 25, and a few block all SMTP on free plans);
- the settings above as environment variables or secrets;
- something to call the run every 10 to 15 minutes. That can be the host's cron
  calling `POST /internal/reminders/run` with the cron secret
  (docs/NOTIFICATIONS.md), or a scheduled job running
  `python -m app.cli.run_reminders`.
