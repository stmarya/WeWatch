# WeWatch — Privacy, Consent, and Data Retention

WeWatch can process camera images, face templates, mood/attendance records,
screen captures, and live audio/video. These data can be sensitive. Use the
system only for a clearly explained, authorized purpose and only where lawful.

## Before enabling monitoring

- Tell every affected person what is collected, why, when, who can see it, where
  it is sent, and how long it is kept.
- Obtain the required affirmative consent before enabling camera monitoring,
  face enrollment, proctoring, remote screen capture, or Telegram alerts. A
  device owner's consent does not automatically cover other people appearing
  on camera or screen.
- Provide a practical way to decline or stop collection. Do not use inferred
  attention, mood, posture, presence, or phone-use labels as the sole basis for
  disciplinary, hiring, access, or other consequential decisions.
- Review applicable privacy, employment, biometric, and cross-border transfer
  requirements with the responsible organization or counsel.

`WEWATCH_PRIVACY_ACKNOWLEDGED=true` is a deployment gate confirming that the
operator has established these procedures. It is not a consent record and
does not replace notice or consent from affected people.

## Data locations and defaults

| Data | Location / transfer | Default behavior |
|---|---|---|
| Face enrollment photos and derived templates | `faces/`; templates are loaded into memory | Face recognition is off until enabled. Production requires a configured expiry period; expired files and corresponding in-memory templates are removed. |
| Mood history | `mood.db` | Persistent mood history is off unless `WEBWATCH_LOG_MOOD=true`. |
| Attendance | `attendance.db` | Stored by the attendance feature; production requires an explicit retention period. |
| Snapshots and gesture screenshots | `static/gallery/` | Explicit snapshots remain local; production requires a gallery retention period. |
| Telegram alert image | Telegram Bot API | Sent only when bot credentials are configured. A local gallery copy is off unless `WEBWATCH_SAVE_ALERT_IMAGES=true`. |
| Remote desktop screenshot | Signaling server, then admin browser | Disabled unless `DESKTOP_AGENT_ALLOW_SCREENSHOTS=true`; enable only with workstation-owner consent. |
| Live meeting media | Browser peers or the configured media service | Use TLS for signaling and media endpoints; do not expose development servers. |

Retention values are set in days:

- `WEBWATCH_RETENTION_GALLERY_DAYS`
- `WEBWATCH_RETENTION_FACE_DAYS`
- `WEBWATCH_RETENTION_MOOD_DAYS`
- `WEBWATCH_RETENTION_ATTENDANCE_DAYS`

In development, `0` disables automatic expiry. Production startup requires
positive, explicitly chosen periods. Gallery and database cleanup runs at
startup and periodically; expired face photos and in-memory templates are
removed by the retention worker. Configure periods to match the published
notice and applicable policy, and verify backups and exported copies separately.

## Access and incident response

- Keep `.env`, database files, `faces/`, and `static/gallery/` out of public
  repositories and web servers.
- Give admin and desktop-agent secrets to authorized operators only; rotate
  them after suspected exposure or staff/device changes.
- Use HTTPS/WSS for remote access, restrict origins and network ports, and
  monitor access to snapshots and biometric records.
- On a deletion request or incident, disable the relevant feature, revoke
  credentials, remove the person's enrollment and stored records, and check
  backups and Telegram for copies that may also need deletion.
