"""Authentication service, one-use recovery tokens and revocable sessions."""
import time
from werkzeug.security import check_password_hash, generate_password_hash
from platform_core.security import PlatformError, opaque_token, token_hash
from platform_core.store import audit, new_id, transaction


def issue_account_token(connection, user_id, purpose):
    now = int(time.time())
    connection.execute('UPDATE account_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL', (now, user_id, purpose))
    raw = opaque_token()
    lifetime = 86400 if purpose == 'verify' else 900
    connection.execute('INSERT INTO account_tokens VALUES (?,?,?,?,?,?,?)',
                       (new_id(), user_id, purpose, token_hash(raw), now + lifetime, None, now))
    return raw


def register(connection, email, password, name):
    # Compute even on duplicate requests to reduce account enumeration by timing.
    encoded = generate_password_hash(password, method='scrypt:32768:8:1')
    with transaction(connection):
        existing = connection.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if existing:
            return None
        user_id = new_id()
        connection.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                           (user_id, email, name, encoded, None, None, int(time.time())))
        raw = issue_account_token(connection, user_id, 'verify')
        audit(connection, user_id, 'account.registered', resource_id=user_id)
    return raw


def request_token(connection, email, purpose):
    with transaction(connection):
        user = connection.execute('SELECT * FROM users WHERE email=? AND disabled_at IS NULL', (email,)).fetchone()
        if not user or purpose == 'verify' and user['email_verified_at'] is not None:
            return None
        return issue_account_token(connection, user['id'], purpose)


def consume_account_token(connection, raw, purpose, password=None):
    now = int(time.time())
    digest = token_hash(raw)
    # Hash before acquiring the write lock; a slow KDF must not block all tenants.
    encoded = generate_password_hash(password, method='scrypt:32768:8:1') if password is not None else None
    with transaction(connection):
        token = connection.execute('''SELECT t.*,u.disabled_at FROM account_tokens t
            JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.purpose=?
            AND t.used_at IS NULL AND t.expires_at>? AND u.disabled_at IS NULL''', (digest, purpose, now)).fetchone()
        if not token:
            raise PlatformError('Token tidak valid, sudah dipakai, atau kedaluwarsa.')
        connection.execute('UPDATE account_tokens SET used_at=? WHERE id=?', (now, token['id']))
        if purpose == 'verify':
            connection.execute('UPDATE users SET email_verified_at=? WHERE id=?', (now, token['user_id']))
            event = 'account.email_verified'
        else:
            if encoded is None:
                raise PlatformError('Password baru wajib diisi.')
            connection.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, token['user_id']))
            connection.execute('UPDATE account_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (now, token['user_id']))
            event = 'account.password_reset'
        audit(connection, token['user_id'], event, resource_id=token['user_id'])
        return token['user_id']


def authenticate(connection, email, password, dummy_hash, lifetime=28800):
    user = connection.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    valid = check_password_hash(user['password_hash'] if user else dummy_hash, password)
    if not user or not valid or user['disabled_at'] is not None:
        raise PlatformError('Email atau password tidak valid.', 401)
    if user['email_verified_at'] is None:
        raise PlatformError('Verifikasi email terlebih dahulu. Anda dapat meminta ulang email verifikasi.', 403)
    now = int(time.time())
    raw = opaque_token()
    with transaction(connection):
        # Re-read account status while holding the write lock; disabling/resetting
        # an account concurrently must not create a session from stale credentials.
        current = connection.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
        if current['disabled_at'] is not None or current['password_hash'] != user['password_hash']:
            raise PlatformError('Email atau password tidak valid.', 401)
        session_id = new_id()
        connection.execute('INSERT INTO account_sessions VALUES (?,?,?,?,?,?,?)',
                           (session_id, user['id'], token_hash(raw), now, now, now + lifetime, None))
        audit(connection, user['id'], 'account.login', resource_id=session_id)
    return raw


def session_user(connection, raw, idle_seconds=1800):
    try:
        digest = token_hash(raw)
    except PlatformError:
        return None
    now = int(time.time())
    user = connection.execute('''SELECT u.*,s.id AS session_id,s.last_seen_at FROM account_sessions s
        JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL
        AND s.expires_at>? AND s.last_seen_at>? AND u.disabled_at IS NULL''', (digest, now, now - idle_seconds)).fetchone()
    if user and now - user['last_seen_at'] >= 60:
        connection.execute('UPDATE account_sessions SET last_seen_at=? WHERE id=? AND revoked_at IS NULL', (now, user['session_id']))
    return user


def revoke_sessions(connection, user_id, session_id=None):
    now = int(time.time())
    with transaction(connection):
        if session_id:
            connection.execute('UPDATE account_sessions SET revoked_at=? WHERE id=? AND user_id=?', (now, session_id, user_id))
        else:
            connection.execute('UPDATE account_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (now, user_id))
        audit(connection, user_id, 'account.logout' if session_id else 'account.logout_all', resource_id=session_id)
