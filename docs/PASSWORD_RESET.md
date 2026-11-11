# Forgot password (D126, D127)

How "Forgot password?" works and what has to be in place before it works in
production. Since D127 it uses a 6-digit code sent by email instead of a link.

## Flow

All four steps are on `/forgot-password`, in one page. Nothing is put in the
address bar, `localStorage` or `sessionStorage`.

1. **Email.** The user enters an email address, and the page calls
   `POST /api/v1/auth/forgot-password`. The answer is always: "If an account
   exists for this email, you'll receive a 6-digit code shortly." The email goes
   out after the response, so the response time reveals nothing either.
   - The code comes from the OS random generator (`secrets.randbelow`).
   - Only its HMAC-SHA256 (keyed with `SECRET_KEY`, bound to its row) is stored, in
     `password_reset_tokens.code_hash`.
   - It works for 10 minutes and allows 5 wrong tries.
   - Asking again expires every unused earlier code (and any unused reset token).
2. **Code.** "Your password reset code — Clinic AI Assistant" arrives. The page
   shows six boxes: typing moves to the next box, Backspace goes back, and a
   pasted or autofilled code fills them all. The sixth digit submits.
   - `POST /auth/verify-reset-otp {email, code}` checks the code under a row
     lock, so parallel guesses are counted one by one.
   - A wrong guess adds one try. The fifth uses the code up.
   - Every refusal is the same `400 RESET_CODE_INVALID`, whether the code is
     wrong, used up or expired, or there's no such account.
   - The right code is used up at once and exchanged for a **reset token**:
     256 bits, valid 10 minutes, only its SHA-256 stored.
   - The reset token can only set a password. It is not a sign-in: no cookie,
     no access token.
   - "Resend code" unlocks after 60 seconds.
3. **New password.** New password and Confirm new password, with show/hide and
   the 8–128 character rule used everywhere. `POST /auth/reset-password
   {token, new_password}` uses the token up with one conditional
   `UPDATE … RETURNING`, so two submissions cannot both succeed. In the same
   transaction it:
   - stores the new bcrypt hash (the same `hash_password` as registration);
   - deletes the user's other unused codes and tokens;
   - revokes every refresh token;
   - sets `users.password_changed_at`;
   - writes an audit entry (`verified_with: email_code`).
4. **Done.** Only after the backend answers 200 (the transaction committed), the
   page says: "Your password has been changed successfully. You can now sign in
   using your new password." It offers **Back to Sign In**. Nobody is signed in
   automatically.

Old reset links (`/reset-password#token=…`) lead to `/forgot-password`. Their
tokens are refused, because they were never earned with a code.

## Who gets what

| Account | Email |
|---|---|
| Active, with a password: Admin, Doctor, Receptionist, Patient or doctor applicant | The code |
| Google-only (no password, D123) | No code. The email says to use **Continue with Google**, then set a password from the account menu |
| Unknown address, or deactivated account | Nothing (the page answers the same) |

## Sessions

- **Refresh tokens:** all revoked, so every browser is signed out at its next refresh.
- **Access tokens** (15-minute JWTs): any issued before `users.password_changed_at`
  is refused at once. Change password (D116) sets the same column, so its "other
  sessions end" now also covers their access tokens.

## Abuse limits

| Limit | Where it is counted |
|---|---|
| 5 requests a minute per IP (forgot-password); 10 per IP (verify and reset) | In the API process |
| 5 wrong tries per code | PostgreSQL, under a row lock |
| At most one code per account every 60 s, and 5 an hour | PostgreSQL, so it holds across instances |

Over the per-account limit the answer stays the same and no email is sent. The
per-IP limit is per process; with several instances, each counts separately.
The per-account limits still hold, and the per-IP limit is only a first filter.
A shared store such as Redis would make it global. It is not added; the
per-account limits are the ones that bound email volume and guessing.

Guessing: 5 tries per code and 5 codes per hour give at most 25 guesses an hour
at 1,000,000 codes for one account.

## Email delivery

- **Sent at once**, through the configured backend (`smtp`, `brevo` on Render
  free, or `outbox` in development). It is not queued in the email outbox: the
  outbox stores bodies in plain text, and this body is a working credential
  (the same choice as for invitations, D87).
- **A failed or unconfigured send** is logged as `password_reset_email_not_sent`
  with the delivery result only. The page still shows the generic answer, and
  the user can ask again after 60 seconds.
- **Never logged or returned:** the code, the reset token and passwords.
- **To check delivery,** run `python -m app.cli.email_check --status` in `backend/`.

## Settings

| Variable | Default |
|---|---|
| `PASSWORD_RESET_CODE_MINUTES` | 10 |
| `PASSWORD_RESET_CODE_MAX_ATTEMPTS` | 5 |
| `PASSWORD_RESET_TOKEN_MINUTES` | 10 (the reset token after a correct code) |
| `PASSWORD_RESET_RESEND_SECONDS` | 60 |
| `PASSWORD_RESET_MAX_PER_HOUR` | 5 |

## Deploy

1. **Migrate the database first.** Migration `c8e1f2a9d374` is additive: three
   new columns on `password_reset_tokens`, and `token_hash` becomes nullable. In
   `backend/`, run `.venv\Scripts\python -m alembic upgrade head`. Do this before
   the new backend starts, because the new code writes the new columns.
2. **Push.** Render and Vercel redeploy.
3. **Check Render's environment.** Email must be configured:
   `EMAIL_BACKEND=brevo`, `BREVO_API_KEY` and a verified `EMAIL_FROM` sender
   (see `docs/EMAIL.md`).
4. **Test it end to end.** Use your own test account, never a patient's:
   1. Request a code and confirm the email arrives.
   2. Enter a wrong code once: it is refused.
   3. Enter the right code, then set a new password.
   4. Confirm the old password fails and the new one works.
   5. Enter the same code again: it is refused.
   6. Request again within a minute: no second email.

Rollback: `alembic downgrade b4d9e2a7c615` (deletes unverified codes, drops the
columns). Then the old link flow's code must be restored too.
