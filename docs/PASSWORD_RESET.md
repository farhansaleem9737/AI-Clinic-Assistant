# Forgot password (D126)

How "Forgot password?" works and what has to be in place before it works in
production.

## Flow

1. **Request.** On `/forgot-password` the user enters an email address, and the
   page calls `POST /api/v1/auth/forgot-password`. The answer is always: "If an
   account exists for this email, you'll receive a password reset link shortly."
   The email goes out after the response, so the response time reveals nothing
   either.
2. **Email.** "Reset your password — Clinic AI Assistant" is sent with a button
   to `FRONTEND_BASE_URL/reset-password#token=…`:
   - The token is 256 bits from the OS random generator.
   - Only its SHA-256 is stored, in `password_reset_tokens`.
   - The link works for 15 minutes, once.
   - Asking again expires the previous unused link.
3. **Link check.** `/reset-password` reads the token from the `#fragment` and
   removes it from the address bar. Browsers never send a fragment to a server
   or in a Referer header. The page then calls `POST /auth/reset-password/check`
   and explains an expired, used or unknown link before anything is typed.
4. **Reset.** `POST /auth/reset-password` uses the token up with one conditional
   `UPDATE … RETURNING`, so two submissions cannot both succeed. In the same
   transaction it:
   - stores the new bcrypt hash (the 8–128 character rule used everywhere);
   - deletes the user's other links;
   - revokes every refresh token;
   - sets `users.password_changed_at`;
   - writes an audit entry.

   Nobody is signed in: the user signs in with the new password.

## Who gets what

| Account | Email |
|---|---|
| Active, with a password: Admin, Doctor, Receptionist, Patient or doctor applicant | The reset link |
| Google-only (no password, D123) | No link. The email says to use **Continue with Google**, then set a password from the account menu |
| Unknown address, or deactivated account | Nothing (the page answers the same) |

## Sessions

- **Refresh tokens:** all revoked, so every browser is signed out at its next refresh.
- **Access tokens** (15-minute JWTs): any issued before `users.password_changed_at`
  is refused at once. Change password (D116) sets the same column, so its "other
  sessions end" now also covers their access tokens.

## Abuse limits

| Limit | Where it is counted |
|---|---|
| 5 requests a minute per IP (forgot-password) and 10 per IP (check and reset) | In the API process |
| At most one link per account every 60 s, and 5 an hour | PostgreSQL, so it holds across instances |

Over the per-account limit the answer stays the same and no email is sent. The
per-IP limit is per process; with several instances, each counts separately.
The per-account limits still hold, and the per-IP limit is only a first filter.
A shared store such as Redis would make it global. It is not added; the
per-account limits are the ones that bound email volume.

## Email delivery

- **Sent at once**, through the configured backend (`smtp`, `brevo` on Render
  free, or `outbox` in development). It is not queued in the email outbox: the
  outbox stores bodies in plain text, and this body is a working credential
  (the same choice as for invitations, D87).
- **A failed or unconfigured send** is logged as `password_reset_email_not_sent`
  with the delivery result only. The page still shows the generic answer, and
  the user can ask again after 60 seconds.
- **Never logged:** the token, the link and passwords.
- **To check delivery,** run `python -m app.cli.email_check --status` in `backend/`.

## Deploy

1. **Migrate the database first.** Migration `b4d9e2a7c615` is additive: a new
   table plus a nullable column. In `backend/`, run
   `.venv\Scripts\python -m alembic upgrade head`. Do this before the new
   backend starts, because the new code reads `users.password_changed_at` on
   every request. The old backend keeps working on the migrated database.
2. **Push.** Render and Vercel redeploy.
3. **Check Render's environment.** `FRONTEND_BASE_URL` must be the https Vercel
   address; it is the link's base. Email must be configured: `EMAIL_BACKEND=brevo`,
   `BREVO_API_KEY` and a verified `EMAIL_FROM` sender (see `docs/EMAIL.md`).
4. **Vercel** sends `Referrer-Policy: no-referrer` and `Cache-Control: no-store`
   for `/reset-password` (`vercel.json`). No new variables are needed.
5. **Test it end to end.** Use your own test account, never a patient's:
   1. Request a link and confirm the email arrives.
   2. Open the link and set a new password.
   3. Confirm the old password fails and the new one works.
   4. Open the link again: it says "already used".
   5. Request again within a minute: no second email.

Rollback: `alembic downgrade f1c6a2d8e573` (drops the table and the column).
