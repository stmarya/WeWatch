# WeWatch user registration

## Routes

- `GET|POST /auth/register` — create a standard user account.
- `GET|POST /auth/login` — user email/password login and backward-compatible admin-token login.
- `GET /account` — authenticated user account page.
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
