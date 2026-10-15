"""Account validation, opaque bearer tokens, and role policy."""
import hashlib
import re
import secrets

ROLES = ('owner', 'admin', 'host', 'member', 'viewer')
ROLE_PERMISSIONS = {
    'owner': ('workspace:read', 'workspace:settings', 'members:manage', 'audit:read', 'ownership:transfer'),
    'admin': ('workspace:read', 'workspace:settings', 'members:manage', 'audit:read'),
    'host': ('workspace:read',),
    'member': ('workspace:read',),
    'viewer': ('workspace:read',),
}
# Meeting/AI/device permission grants are NOT implemented by this foundation.
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")


class PlatformError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def email_address(value):
    if not isinstance(value, str) or len(value) > 254 or not _EMAIL.fullmatch(value.strip()):
        raise PlatformError('Alamat email tidak valid.')
    email = value.strip().lower()
    local, domain = email.rsplit('@', 1)
    if len(local) > 64 or '..' in email or any(not part for part in domain.split('.')):
        raise PlatformError('Alamat email tidak valid.')
    return email


def password_value(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise PlatformError('Gunakan passphrase 12–128 karakter.')
    return value


def bounded_name(value, default=None):
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise PlatformError('Nama harus berisi 1–80 karakter.')
    if any(ord(character) < 32 for character in value):
        raise PlatformError('Nama tidak boleh mengandung karakter kontrol.')
    return value.strip()


def opaque_token():
    return secrets.token_urlsafe(32)


def token_hash(value):
    if not isinstance(value, str) or not 20 <= len(value) <= 200:
        raise PlatformError('Token tidak valid atau kedaluwarsa.', 400)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def can_invite(actor_role, invited_role):
    return invited_role in ('host', 'member', 'viewer') and actor_role in ('owner', 'admin') or invited_role == 'admin' and actor_role == 'owner'


def can_manage_member(actor_role, target_role, new_role=None):
    if target_role == 'owner':
        return False
    if actor_role == 'owner':
        return new_role is None or new_role in ('admin', 'host', 'member', 'viewer')
    return actor_role == 'admin' and target_role in ('host', 'member', 'viewer') and (new_role is None or new_role in ('host', 'member', 'viewer'))
