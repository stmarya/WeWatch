# WeWatch user accounts

## Routes

| Route | Purpose |
| --- | --- |
| `GET/POST /auth/register` | Create an account (optional avatar choice). Sends a verification email. |
| `GET/POST /auth/login` | Email/password login and admin-token login. |
| `GET /auth/verify-email/<token>` | Confirm an email address (24 h, single use). |
| `GET/POST /auth/forgot-password` | Request a reset link. Same response whether or not the email exists. |
| `GET/POST /auth/reset-password/<token>` | Set a new password (1 h, single use). Revokes all sessions. |
| `GET /auth/confirm-email/<token>` | Apply a pending email change; the old address is notified. |
| `GET /account` | Account page: profile, avatar, email, password, details, data & privacy. |
| `POST /account/profile` | Name, bio (≤280), catalog avatar. |
| `POST /account/avatar/upload` / `remove` | Upload or remove a profile photo. |
| `POST /account/email` | Request an email change (current password required, confirmed by link). |
| `POST /account/verify-email/resend` | Resend the verification link. |
| `POST /account/password` | Change password (current password required); other sessions revoked. |
| `POST /account/export` | Download account data as JSON. |
| `POST /account/delete` | Permanently delete the account (password + typing `HAPUS`). |
| `GET /account/meeting` | Join WebRTC Meet with the account's name and avatar (signed 5-minute ticket). |
| `GET /media/avatars/<id>.webp` | Serve uploaded photos (random IDs, `default-src 'none'`). |
| `POST /auth/logout` | CSRF-protected logout. |

`/` and all monitoring, gallery, AI, and remote-control endpoints remain admin-only.

## Storage

- **SQLite** (default): `WEBWATCH_USERS_DB` (default `users.db`).
- **PostgreSQL**: set `WEBWATCH_DATABASE_URL=postgresql://…` (requires `psycopg[binary,pool]`). Use this when running more than one web replica. `docker-compose.scale.yml` includes a `postgres` service.
- Tables are created and migrated automatically on startup. Accounts that existed before email verification are marked verified.

`users`: `id`, `display_name`, `email` (normalized, case-insensitively unique), `password_hash` (scrypt), `role`, `is_active`, `avatar` (catalog ID or `upload:<id>`), `bio`, `session_epoch`, `email_verified_at`, `created_at`, `updated_at`, `last_login_at`.

`auth_tokens`: SHA-256 hashes of single-use tokens (`verify_email`, `change_email`, `reset_password`) with expiry; issuing a new token revokes older unused ones of the same purpose; rows cascade on account deletion.

Uploaded photos live in `WEBWATCH_UPLOAD_DIR/avatars` (default `./uploads/avatars`, git-ignored), never in `static/`.

## Email

`WEBWATCH_MAIL_BACKEND`: `smtp` (via `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY=starttls|ssl|none`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`), `console` (development; links are written to the log), or `memory` (tests). Links are built from `WEBWATCH_PUBLIC_URL`.

Set `WEBWATCH_REQUIRE_EMAIL_VERIFICATION=true` to block login until the address is verified.

## Avatars

- 40 bundled CC0 DiceBear SVGs (`static/avatars/`, see `LICENSE.md`); the server only accepts catalog IDs.
- Photo uploads: JPG/PNG/WebP, ≤2 MB, ≤4096×4096. Every upload is decoded and re-encoded with Pillow to a 256×256 WebP, which strips EXIF/GPS metadata and neutralizes polyglot files. The old file is deleted when replaced.

## Meeting integration

`/account/meeting` issues a short-lived room ticket (`WEBRTC_SECRET_KEY`) with `identity=user:<id>` and a signed `profile` (`name`, absolute `avatar` URL). The signaling server verifies the ticket and uses the signed name/avatar instead of client-supplied values; participants show the avatar and a "WeWatch account" label. Guests without a ticket still work unless `WEBRTC_REQUIRE_JOIN_TOKEN=true`.

## Security controls

- Password 12–128 chars with letters and digits; salted scrypt; constant-time comparison; dummy-hash work for unknown emails.
- Generic login failure and forgot-password responses (no account enumeration).
- Rate limits for login, registration, email sending, account security actions, and uploads. Limits are shared through Redis (`WEBWATCH_RATE_LIMIT_REDIS_URL` or `REDIS_URL`) with a local fallback and 30 s circuit breaker if Redis is down.
- Pre-auth and session CSRF tokens on every state-changing form; session rotation on login/password change.
- `session_epoch` revokes other sessions after password change/reset.
- Email changes take effect only after confirming the new address; the old address receives a notice. Password changes and account deletion also send notices.
- Export and delete are POST-only, CSRF-protected; delete requires the current password.
- HttpOnly, SameSite=Lax, optional Secure cookies; 12-hour session lifetime; request size cap.

## Production checklist

1. Set different random `WEBWATCH_SESSION_SECRET` and `WEBRTC_SECRET_KEY` (≥32 bytes).
2. Set `WEBWATCH_PUBLIC_URL` to the HTTPS origin and `WEBWATCH_COOKIE_SECURE=true`.
3. Configure SMTP and set `WEBWATCH_REQUIRE_EMAIL_VERIFICATION=true`.
4. Use PostgreSQL (`WEBWATCH_DATABASE_URL`) and Redis for multi-replica deployments; back up both plus `WEBWATCH_UPLOAD_DIR`.
5. Set `WEBRTC_CLIENT_URL` to the public meeting URL.
6. Monitor rate-limit events, authentication failures, and email delivery errors.
