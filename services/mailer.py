"""Transactional email delivery (verification, password reset, notices).

Backends, selected with ``WEBWATCH_MAIL_BACKEND``:

- ``smtp``    – deliver through ``SMTP_HOST``/``SMTP_PORT`` (STARTTLS by default).
- ``console`` – log the message (development only; links appear in the log).
- ``memory``  – keep messages in ``outbox`` (tests).

Default: ``smtp`` when ``SMTP_HOST`` is set, otherwise ``console``.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import logging
import os
import smtplib
import ssl
import threading


@dataclass(frozen=True)
class SentMail:
    to: str
    subject: str
    body: str


outbox: list[SentMail] = []
_lock = threading.Lock()


def _backend() -> str:
    configured = os.getenv("WEBWATCH_MAIL_BACKEND", "").strip().lower()
    if configured:
        return configured
    return "smtp" if os.getenv("SMTP_HOST", "").strip() else "console"


def is_configured_for_production() -> bool:
    return _backend() == "smtp"


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns False instead of raising on failure."""
    backend = _backend()
    if backend == "memory":
        with _lock:
            outbox.append(SentMail(to, subject, body))
        return True
    if backend == "console":
        logging.warning("[mail:console] To: %s | Subject: %s\n%s", to, subject, body)
        return True
    if backend != "smtp":
        logging.error("Unknown WEBWATCH_MAIL_BACKEND=%s", backend)
        return False

    message = EmailMessage()
    message["From"] = os.getenv("SMTP_FROM", "WeWatch <no-reply@localhost>")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    security = os.getenv("SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
    try:
        context = ssl.create_default_context()
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, context=context, timeout=15)
        else:
            client = smtplib.SMTP(host, port, timeout=15)
        with client:
            if security == "starttls":
                client.starttls(context=context)
            if user:
                client.login(user, password)
            client.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        logging.error("Failed to send email to %s: %s", to, exc)
        return False


# --------------------------------------------------------------- templates
def send_verification_email(to: str, name: str, link: str) -> bool:
    return send_mail(
        to,
        "Verifikasi email akun WeWatch",
        f"Halo {name},\n\nKonfirmasi alamat email kamu dengan membuka link berikut "
        f"(berlaku 24 jam):\n\n{link}\n\nAbaikan email ini jika kamu tidak membuat akun WeWatch.\n",
    )


def send_email_change_confirmation(to: str, name: str, link: str) -> bool:
    return send_mail(
        to,
        "Konfirmasi email baru akun WeWatch",
        f"Halo {name},\n\nBuka link berikut untuk menjadikan alamat ini email login "
        f"akun WeWatch kamu (berlaku 24 jam):\n\n{link}\n\nAbaikan jika kamu tidak memintanya.\n",
    )


def send_email_changed_notice(to: str, name: str, new_email: str) -> bool:
    return send_mail(
        to,
        "Email akun WeWatch telah diganti",
        f"Halo {name},\n\nEmail login akun WeWatch kamu baru saja diganti menjadi {new_email}.\n"
        "Jika ini bukan kamu, segera reset password dan hubungi administrator.\n",
    )


def send_password_reset_email(to: str, name: str, link: str) -> bool:
    return send_mail(
        to,
        "Reset password WeWatch",
        f"Halo {name},\n\nKami menerima permintaan reset password. Buka link berikut "
        f"(berlaku 1 jam):\n\n{link}\n\nAbaikan email ini jika kamu tidak memintanya; "
        "password kamu tidak akan berubah.\n",
    )


def send_password_changed_notice(to: str, name: str) -> bool:
    return send_mail(
        to,
        "Password WeWatch telah diganti",
        f"Halo {name},\n\nPassword akun WeWatch kamu baru saja diganti dan semua sesi lain telah "
        "dikeluarkan. Jika ini bukan kamu, segera gunakan fitur lupa password.\n",
    )


def send_account_deleted_notice(to: str, name: str) -> bool:
    return send_mail(
        to,
        "Akun WeWatch telah dihapus",
        f"Halo {name},\n\nAkun WeWatch kamu dan data profilnya telah dihapus permanen.\n",
    )
