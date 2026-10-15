"""Explicit SMTP delivery or loopback-only private file delivery for development."""
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import ssl
from urllib.parse import urlsplit
import uuid


class MailDeliveryError(Exception):
    pass


class Mailer:
    def __init__(self, config):
        self.config = config
        self.transport = config['MAIL_TRANSPORT']
        if self.transport not in ('disabled', 'smtp', 'file'):
            raise ValueError('Unsupported mail transport')
        if self.transport == 'file':
            if config['ENVIRONMENT'] != 'development' or urlsplit(config['PUBLIC_URL']).hostname not in ('localhost', '127.0.0.1', '::1'):
                raise ValueError('File mail delivery is only allowed for loopback development')
            directory = Path(config['MAIL_DIRECTORY']).expanduser().absolute()
            if directory.is_symlink():
                raise ValueError('Mail directory must not be a symlink')
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            if os.name != 'nt' and directory.stat().st_mode & 0o077:
                raise ValueError('Mail directory must be private (mode 0700)')
            self.directory = directory

    @property
    def ready(self):
        return self.transport == 'file' or (self.transport == 'smtp' and bool(self.config['SMTP_HOST']))

    def send(self, recipient, subject, body):
        if not self.ready:
            raise MailDeliveryError('Mail delivery is not configured')
        message = EmailMessage()
        message['To'] = recipient
        message['From'] = self.config['MAIL_FROM']
        message['Subject'] = subject
        message.set_content(body)
        try:
            if self.transport == 'file':
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                fd = os.open(self.directory / (uuid.uuid4().hex + '.eml'), flags, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    output.write(message.as_string())
                return
            with smtplib.SMTP(self.config['SMTP_HOST'], self.config['SMTP_PORT'], timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if self.config['SMTP_USER']:
                    smtp.login(self.config['SMTP_USER'], self.config['SMTP_PASSWORD'])
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            # Do not include server exception text: it may contain recipients,
            # credentials, or bearer links. Applications emit a generic error.
            raise MailDeliveryError('Mail delivery failed') from exc
