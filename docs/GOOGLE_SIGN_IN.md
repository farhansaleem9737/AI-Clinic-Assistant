# Continue with Google: setup (D123)

The code is in place and tested with a simulated Google. Real sign-in needs a
Google OAuth client that only you can create. Nothing secret goes in Git or in
the frontend.

## How it works

- **The browser only talks to the app's own origin.** The Vite dev server
  (development) or Vercel (production) forwards `/api/*` to FastAPI.
- **Google's callback lands on that same origin:**
  `<frontend origin>/api/v1/auth/google/callback`.
  So every cookie is first-party and the existing `SameSite=Strict` session
  cookie keeps working.
- **Flow:** Authorization Code with PKCE (S256), `state` bound to the browser by
  a cookie, and a `nonce`. The ID token is verified by the backend (signature,
  audience, issuer, expiry, nonce, verified email).
- **Scopes:** `openid email profile` only. The app requests no Google API
  access and stores no Google tokens.

| Where | Callback URL to register in Google |
|---|---|
| Local development | `http://localhost:5173/api/v1/auth/google/callback` |
| Production (Vercel) | `https://<your-vercel-domain>/api/v1/auth/google/callback` |

**Authorized JavaScript origins are not needed:** no Google script runs in the
browser.

### Google with the address of an existing account (D128)

Who a Google sign-in is, in order:

1. **Google's `sub` is already linked** to an account: that account, with its own
   roles. A changed Gmail address doesn't matter, because `sub` never changes.
2. **Not linked, but an account has the same email:** nothing is linked
   automatically, because a matching email proves nothing about who controls the
   account. The browser goes to **Link your Google account** (`/login/link-google`),
   and the owner proves the account is theirs:
   - **Patients and doctor applicants** use the account's password, or a 6-digit
     code emailed to the account's own address.
   - **Doctors, receptionists and admins** must use the password.
   - Limits: the step is bound to that account and that Google `sub`, lasts 15
     minutes and allows 5 wrong tries. A code lasts 10 minutes, and a new one can
     be sent after 60 seconds.

   When the proof is right, one transaction links Google (`oauth_identities`,
   unique per Google `sub`) to the same user id, writes an audit entry and starts
   the normal session. Then a notice email goes to the account. Nothing else
   changes: the user id, roles, profile, appointments, records, preferences and
   password all stay. "Don't link" ends the step and changes nothing.
3. **Neither:** the Google registration form, as before. It offers patient or
   doctor applicant only, and a doctor applicant still waits for review.

Refused at any step: deactivated accounts, a Google account already linked to
another user, and a login that already has a different Google account.

## 1. Google Cloud Console (you)

1. **Open the console.** Go to https://console.cloud.google.com/ and sign in with
   the Google account that should own the app.
2. **Create a project.** Use the project picker (top bar) › **New project**.
   Name it, e.g. `Clinic AI Assistant`, then **Create** and select it.
3. **Open Google Auth Platform.** Use the menu ☰ › **APIs & Services** ›
   **OAuth consent screen**, or search for "Google Auth Platform". Click
   **Get started** if asked.
4. **Branding:**
   - **App name:** `Clinic AI Assistant`.
   - **User support email:** yours.
   - **Logo:** optional. It triggers Google's brand verification if you publish.
   - **App domain** (production only): home page `https://<your-vercel-domain>`,
     privacy policy `https://<your-vercel-domain>/privacy`, terms
     `https://<your-vercel-domain>/terms`.
   - **Authorized domains:** `<your-vercel-domain>` without `https://`. For a
     `*.vercel.app` address, add the full `your-app.vercel.app`.
   - **Developer contact:** your email.
5. **Audience:** **External**. While the app is in **Testing**, only the
   addresses you add under **Test users** can sign in (up to 100). Add your own
   Google account and every tester.
6. **Data Access (scopes):** **Add or remove scopes** and tick only
   `.../auth/userinfo.email`, `.../auth/userinfo.profile` and `openid`. These are
   non-sensitive scopes, so no security review is needed.
7. **Clients:**
   1. **Create client**.
   2. **Application type:** **Web application**.
   3. **Name:** e.g. `Clinic web (FastAPI)`.
   4. **Authorized JavaScript origins:** leave empty.
   5. **Authorized redirect URIs:** add both URLs from the table above, exactly:
      same scheme and port, no trailing slash.
   6. **Create**.
8. **Copy the credentials.** Copy the **Client ID** (`….apps.googleusercontent.com`)
   and the **Client secret**. The secret is shown once; you can create a new one
   later under the client.
9. **Going live** (when real patients should sign in): **Audience** ›
   **Publish app**. With only the three basic scopes and no logo, Google
   publishes it without review. With a logo, expect brand verification (a few
   days).

## 2. Local backend (you)

1. **Edit `backend/.env`** and add the following, pasting the values from
   step 8:

   ```
   GOOGLE_OAUTH_ENABLED=true
   GOOGLE_OAUTH_CLIENT_ID=<Client ID>
   GOOGLE_OAUTH_CLIENT_SECRET=<Client secret>
   ```

   `GOOGLE_OAUTH_REDIRECT_URI` is optional. It defaults to `FRONTEND_BASE_URL` +
   `/api/v1/auth/google/callback`, which is `http://localhost:5173/...` in
   development.
2. **Apply the migration** (see section 5) to the database that `.env` uses.
3. **Restart FastAPI:** `uvicorn app.main:app --reload` in `backend/`.
4. **Check the configuration:**
   - `http://localhost:5173/api/v1/auth/providers` shows `{"google": true}`.
   - If the backend refuses to start with "GOOGLE_OAUTH_ENABLED needs
     GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET", a value is missing.

## 3. Render: API (you)

1. **Environment variables:** in Render › `clinic-api` › **Environment**, set
   `GOOGLE_OAUTH_ENABLED=true` and add `GOOGLE_OAUTH_CLIENT_ID` and
   `GOOGLE_OAUTH_CLIENT_SECRET`. `render.yaml` lists them; `sync: false`
   means you enter them in the dashboard.
2. **Frontend URL:** make sure `FRONTEND_BASE_URL=https://<your-vercel-domain>`
   is set. It determines the callback URL and where the browser lands after
   Google.
3. **Redeploy:** saving environment variables redeploys on Render; otherwise use
   **Manual Deploy**.
4. **Check:**
   - `https://<your-vercel-domain>/api/v1/auth/providers` shows `{"google": true}`.
   - Cookies are `Secure` automatically in production (`ENVIRONMENT=production`).

## 4. Vercel: frontend (you)

**No new variables:** the client ID and secret live only on the backend.
`vercel.json` already forwards `/api/*` to Render, which carries the callback.
**No rebuild is needed for Google.** Rebuild only to deploy this release's
frontend code.

## 5. Database (you)

Linking at sign-in (D128) needs migration `d4a7e2c19b58`. It is additive: three
new columns on `oauth_flows`, and the step kind `link` allowed. Apply it with the
other migrations (`alembic upgrade head`).

The first Google migration:

The migration is `f1c6a2d8e573`:
- it adds the tables `oauth_identities` and `oauth_flows`;
- it makes `users.password_hash` nullable, for Google-only accounts.

It is additive: no existing row changes.

1. **Back up first** with `pg_dump`, as before your other migrations.
2. **Apply it:** in `backend/`, run `.venv\Scripts\python -m alembic upgrade head`.
   If Neon is still on `d5e9a3c7b418`, this also applies `e3b7c1d9f240` (D120).
3. **Verify:** `/health` reports `"schema": "current"`, and
   `SELECT version_num FROM alembic_version` returns `f1c6a2d8e573`.
4. **Rollback:** `alembic downgrade e3b7c1d9f240`. It refuses while a Google-only
   account exists; those users must set a password first.

## 6. Browser checklist

| # | Test | Expected |
|---|---|---|
| 1 | Sign in › **Continue with Google** with a test-user account that has no clinic account | "Finish creating your account" form, with the email locked to the Google address |
| 2 | Complete it as a Patient | Lands on the patient dashboard, signed in |
| 3 | Sign out, then **Continue with Google** again | Signed straight in |
| 4 | **Sign up with Google** as a Doctor | Doctor-applicant view, application waiting for review (not an approved doctor) |
| 5 | Google sign-in with the address of an existing password account | "Link your Google account": enter the password (or, for a patient, an emailed code), then you're signed in to the same account and "Google sign-in was connected" arrives by email |
| 5b | Sign out, then Google sign-in again with that account | Signed straight in, to the same dashboard and data as the password sign-in |
| 6 | Sign in with the password, then Account › Connected accounts › **Link Google account** (enter the password if asked) | "Your Google account is now linked"; Google sign-in now works for it |
| 7 | Cancel on Google's page | Back on Sign in with "Google sign-in was cancelled" |
| 8 | Press Back to the callback URL, or reload it | "expired or was already used"; nobody is signed in |
| 9 | Unlink Google on an account that has a password | Unlinked; password sign-in still works |
| 10 | Deactivate a linked user (admin), then try Google sign-in as them | "This account can't sign in" |
| 11 | Email and password sign-in | Unchanged |

Never paste the client secret into chat, issues or the frontend.
