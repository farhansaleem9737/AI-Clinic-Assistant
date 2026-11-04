# Notifications, reminders and follow-ups (D108)

In-app only: no e-mail, SMS, WhatsApp or push. PostgreSQL is the only store, so a
user sees every notification the next time they sign in, on any device.

## Data

| Table | What it holds |
|---|---|
| `notifications` | One row per user and message. `dedupe_key` is set for scheduled ones: a unique index on (user_id, dedupe_key) keeps a reminder from existing twice. A partial index serves the unread count. |
| `notification_preferences` | Optional categories a user switched off. No row means everything is on. |
| `follow_ups` | A follow-up visit recorded as due by a date. Only a date: no reason, note or interval. |

Migration `c4f8a2d61b93` is additive only: one nullable column, two indexes and two new tables.

Messages carry dates and times only, never patients' names, reasons or clinical
details. Links are limited to known pages of this app (`notification_service.safe_link`,
mirrored in `frontend/src/utils/notifications.js`), and the database also refuses
external URLs.

## Who is told what

The person who acted is never notified about their own action.

| Event | Patient | Doctor | Front desk | Admin |
|---|---|---|---|---|
| Booked by staff on the patient's behalf | ✓ | ✓ (essential) | | |
| Patient books online | | ✓ (essential) | | |
| Confirmed | ✓ | | | |
| Checked in | | ✓ | | |
| Rescheduled | ✓ | ✓ (old and new doctor) | ✓ if the patient did it online | |
| Cancelled | ✓ | ✓ | ✓ if the patient did it online | |
| Appointment reminder | 24 h and 1 h before | 1 h before | | |
| Follow-up due | 7 days before the due date | | | |
| Schedule changed by the clinic | | ✓ (essential) | | |
| New doctor application | | | | ✓ reviewers (essential) |
| Application approved or rejected | | | | applicant (essential) |

**Schedule changes cannot affect booked patients.** The schedule service refuses any
change that would leave a booked appointment outside working hours, so there is no
"your appointment moved" case to notify.

**Preferences:** users can switch off three optional categories in the bell's
settings view:
- appointment updates (confirmed, rescheduled, cancelled, booked for you, checked in);
- reminders;
- follow-ups.

Essential notifications are always sent.

## Reminders

`reminder_service.run` reads the database as it is now:
- **Which appointments:** only active ones (requested, scheduled or confirmed) that
  start within the largest offset. Cancelled appointments, including the old row of
  a rescheduled one, are never picked up.
- **Which reminder is sent:**
  - Of the offsets, the run sends the closest one that has started.
  - It sends that one only if the appointment was booked before that reminder's
    moment. A booking made 3 hours ahead gets the 1-hour reminder only; one made
    30 minutes ahead gets none.
- **Time arithmetic:** times are compared as UTC instants, so daylight-saving
  changes cannot shift a reminder. Messages show the doctor's department timezone.
- **Duplicates:** every reminder is inserted with `ON CONFLICT DO NOTHING` on its
  key, `reminder:<appointment>:<offset>:<role>:<start>`. So a run can be repeated,
  retried or overlapped safely, and a moved appointment (new row, new start) is
  reminded about afresh.
- **Follow-ups:**
  - The patient is reminded once per due date, from `FOLLOW_UP_REMINDER_DAYS` before it.
  - No reminder is sent if they already booked: an active appointment created after
    the follow-up, with the same doctor.
  - No reminder is sent if it was dismissed, or once it is 30 days overdue.
  - The message says the visit is not booked yet.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `REMINDER_OFFSETS_MINUTES` | `1440,60` | Patient reminders, minutes before the start |
| `DOCTOR_REMINDER_OFFSETS_MINUTES` | `60` | Doctor reminders |
| `FOLLOW_UP_REMINDER_DAYS` | `7` | Lead time for follow-ups |
| `REMINDERS_OIDC_AUDIENCE` | unset | Production: the run URL (see below) |
| `REMINDERS_INVOKER_EMAIL` | unset | Production: the scheduler's service account |
| `REMINDERS_CRON_SECRET` | unset | Development or another scheduler: secret in `X-Reminders-Secret` |

With none of the last three set, `POST /api/v1/internal/reminders/run` answers 404.

### Running it

- **Locally:** `python -m app.cli.run_reminders` (safe to repeat).
- **On Cloud Run:** nothing runs inside the API on a timer. Instances can scale to
  zero, and every instance would otherwise run its own copy. Cloud Scheduler calls
  the endpoint instead, with a Google-signed OIDC token. The app checks that token's
  audience and service-account e-mail itself, because the service also has to stay
  public for the frontend.

Not done yet: provision these yourself.

```bash
PROJECT=your-project
SERVICE_URL=https://your-service-xxxx.a.run.app        # the backend's Cloud Run URL
RUN_URL="$SERVICE_URL/api/v1/internal/reminders/run"

# 1. An identity for the scheduler (it needs no roles: the app checks its token).
gcloud iam service-accounts create reminder-scheduler --project=$PROJECT \
  --display-name="Clinic reminder scheduler"

# 2. Tell the backend who may call the run (Cloud Run environment variables).
gcloud run services update YOUR_SERVICE --region=asia-southeast1 --project=$PROJECT \
  --update-env-vars="REMINDERS_OIDC_AUDIENCE=$RUN_URL,REMINDERS_INVOKER_EMAIL=reminder-scheduler@$PROJECT.iam.gserviceaccount.com"

# 3. The schedule: every 15 minutes, 06:00–22:59 clinic time (see "Cost" below).
gcloud scheduler jobs create http clinic-reminders --project=$PROJECT --location=asia-southeast1 \
  --schedule="*/15 6-22 * * *" --time-zone="Asia/Karachi" \
  --uri="$RUN_URL" --http-method=POST \
  --oidc-service-account-email="reminder-scheduler@$PROJECT.iam.gserviceaccount.com" \
  --oidc-token-audience="$RUN_URL" \
  --attempt-deadline=120s --max-retry-attempts=3 --min-backoff=30s
```

**Permissions:**
- The person creating the job needs `roles/cloudscheduler.admin` and
  `roles/iam.serviceAccountUser` on `reminder-scheduler`.
- Cloud Scheduler's own service agent mints the OIDC token. Its role is granted
  automatically when the Cloud Scheduler API is enabled.
- If the backend is ever made private (`--no-allow-unauthenticated`), also grant
  `reminder-scheduler` the `roles/run.invoker` role on the service.

**Checking it:**
- Each run logs `reminder_run` with counts and duration.
- The endpoint returns the same counts.
- Refused calls log `reminder_run_refused`.

### Cost

**Cloud Scheduler:**
- 3 jobs per billing account per month are free; this is one job.
- Each further job costs about US$0.10 a month.
- The project needs a billing account, which Cloud Run already requires.

**Neon (the bigger factor):**
- Each run wakes the database compute, which then stays up for its 5-minute
  auto-suspend window.
- Every 15 minutes, around the clock, keeps it awake roughly a third of the time
  (~240 compute hours a month).
- Limiting runs to clinic hours, as above, cuts that by about a third.
- When to expect reminders:
  - Reminders due overnight go out at 06:00.
  - The 1-hour reminder arrives 45–60 minutes before the start.
  - Early-morning appointments still get theirs from the 06:00 run on.
- Lower `--schedule` frequency if compute hours matter more than exact timing.

## Frontend

**Notification bell** (`components/layout/NotificationBell.jsx`):
- **Unread count:** refreshed every 2 minutes while the tab is visible, and when
  the user returns to the tab (at most every 15 s). Hidden tabs make no requests.
- **Panel:** recent notifications, with older ones on request. Read and unread look
  different, and opening one marks it read and goes to its page. Also has mark all
  as read, error and retry, keyboard handling (Escape closes and returns focus),
  and a settings view for the three categories.

**Follow-ups** appear on Appointment Detail, in the doctor card
(`components/appointments/FollowUpPanel.jsx`):
- The appointment's doctor or the clinic records or changes the date.
- The patient sees "due by … — not booked yet", with Book follow-up and Dismiss.
