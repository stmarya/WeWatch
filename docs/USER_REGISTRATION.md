# WeWatch user registration

## Routes

- `GET|POST /auth/register` — create a standard user account.
- `GET|POST /auth/login` — user email/password login and backward-compatible admin-token login.
- `GET /account` — authenticated account page: view profile, avatar, and account details.
- `POST /account/profile` — update display name, bio (max 280 chars), and avatar.
- `POST /account/email` — change login email; requires the current password.
- `POST /account/password` — change password; requires the current password and revokes all other sessions.
- `POST /auth/logout` — CSRF-protected logout.
- `/` and all monitoring, gallery, AI, and remote-control endpoints remain admin-only.

## Database

The default database is `users.db` in the repository root and can be changed with `WEBWATCH_USERS_DB`. The file is ignored by Git through the existing `*.db` rule.

`users` columns:

- UUID-style random `id`.
- Normalized unique `email` with case-insensitive uniqueness.
- `display_name`.
- Scrypt `password_hash`; plaintext passwords are never stored or logged.
- Server-assigned `role` (`user` by default).
- `is_active` status.
- UTC `created_at`, `updated_at`, and `last_login_at` timestamps.
- `avatar` — ID from the bundled catalog in `static/avatars/` (see `services/avatars.py`); new users get a stable default.
- `bio` — optional short profile text.
- `session_epoch` — incremented on password change; sessions with an older epoch are rejected.

Existing databases are migrated automatically on startup (missing columns are added).

## Avatars

Avatars are CC0 1.0 SVGs generated once with DiceBear (Notionists, Lorelei, Pixel Art, Thumbs) and served locally, so there is no runtime dependency on a third-party API and no tracking of users by an external avatar service. The server only accepts IDs from the catalog, never URLs or paths. See `static/avatars/LICENSE.md` before adding styles; CC BY 4.0 styles require visible attribution.

SQLite uses WAL mode, foreign-key enforcement, parameterized queries, busy timeout, and short-lived connections. For multi-replica production deployments, replace the local SQLite store with a shared transactional database.

## Security controls

- Password length: 12–128 characters with at least one letter and one number.
- Email and display-name normalization and server-side validation.
- Password hashing with salted `hashlib.scrypt` (`N=32768`, `r=8`, `p=1`) and constant-time verification.
- Constant hash work for unknown-email authentication to reduce timing-based enumeration.
- Generic login failure message.
- Case-insensitive unique email and safe duplicate handling.
- Registration and login rate limiting.
- Pre-authentication CSRF tokens for login/registration.
- Session rotation after successful authentication.
- HttpOnly, SameSite=Lax, optional Secure cookies, and 12-hour session expiry.
- CSRF protection for authenticated state-changing requests, including logout.
- Email and password changes require the current password and are rate limited per account.
- Password change rotates the current session and revokes other sessions via `session_epoch`.
- RBAC separation: registered users cannot access admin camera, AI, gallery, or remote-control endpoints.
- Security headers include clickjacking, MIME sniffing, referrer, permissions, HSTS on HTTPS, and a restrictive framing/form CSP.

## Production checklist

1. Set `WEBWATCH_SESSION_SECRET` and `WEBRTC_SECRET_KEY` to different random values of at least 32 bytes.
2. Set `WEBWATCH_COOKIE_SECURE=true` behind HTTPS.
3. Back up `WEBWATCH_USERS_DB` and restrict its filesystem permissions.
4. Use a shared database before running multiple web replicas.
5. Add email verification and password-reset delivery before public internet onboarding.
6. Monitor registration/login rate-limit events and authentication failures.
7. Never promote a user to admin from browser-submitted registration fields; roles must be managed server-side.
