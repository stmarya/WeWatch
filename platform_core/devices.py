"""Browser-session pairing and local preview intentions, never remote/device grants."""
import time
from platform_core import workspaces
from platform_core.security import PlatformError, bounded_name, opaque_token, token_hash
from platform_core.store import audit, new_id, transaction

PAIR_TTL = 300
PREVIEW_TTL = 600
POLICY_VERSION = 'local-preview-v1'
PREVIEW_CAPABILITIES = ('camera_preview', 'microphone_preview')
UNAVAILABLE = ('local_ai', 'remote_screen', 'remote_input', 'remote_screenshot', 'remote_command')


def live_session(connection, session_id, user_id):
    now = int(time.time())
    row = connection.execute('''SELECT s.* FROM account_sessions s JOIN users u ON u.id=s.user_id
        WHERE s.id=? AND s.user_id=? AND s.revoked_at IS NULL AND s.expires_at>?
        AND s.last_seen_at>? AND u.disabled_at IS NULL AND u.email_verified_at IS NOT NULL''',
        (session_id, user_id, now, now - 1800)).fetchone()
    if not row:
        raise PlatformError('Sesi perangkat tidak lagi aktif. Login dan pairing ulang.', 401)
    return row


def eligible(connection, workspace_id, user_id, session_id):
    member = workspaces.access(connection, workspace_id, user_id)
    live_session(connection, session_id, user_id)
    if member['role'] == 'viewer':
        raise PlatformError('Viewer hanya dapat melihat workspace; pairing/preview tidak diizinkan.', 403)
    return member


def own_device(connection, workspace_id, device_id, user_id, session_id):
    member = eligible(connection, workspace_id, user_id, session_id)
    device = connection.execute('''SELECT * FROM browser_devices WHERE id=? AND workspace_id=?
        AND user_id=? AND session_id=? AND revoked_at IS NULL''',
        (device_id, workspace_id, user_id, session_id)).fetchone()
    if not device:
        raise PlatformError('Pairing browser tidak ditemukan pada sesi ini.', 404)
    if device['role_at_pairing'] != member['role']:
        raise PlatformError('Role berubah; pairing ulang diperlukan.', 403)
    return device


def begin_pairing(connection, workspace_id, user_id, session_id, name):
    name = bounded_name(name)
    with transaction(connection):
        member = eligible(connection, workspace_id, user_id, session_id)
        active = connection.execute('SELECT id FROM browser_devices WHERE workspace_id=? AND session_id=? AND revoked_at IS NULL', (workspace_id, session_id)).fetchone()
        if active:
            raise PlatformError('Sesi browser ini sudah dipasangkan. Cabut pairing sebelum mengganti.', 409)
        now = int(time.time())
        connection.execute('UPDATE device_pairings SET revoked_at=? WHERE workspace_id=? AND session_id=? AND used_at IS NULL AND revoked_at IS NULL', (now, workspace_id, session_id))
        raw, pairing_id = opaque_token(), new_id()
        connection.execute('INSERT INTO device_pairings VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (pairing_id, workspace_id, user_id, session_id, name, member['role'], token_hash(raw), now, now + PAIR_TTL, None, None))
        audit(connection, user_id, 'browser.pairing_requested', workspace_id, pairing_id)
        return {'id': pairing_id, 'token': raw, 'expires_at': now + PAIR_TTL, 'workspace_id': workspace_id, 'name': name}


def inspect_pairing(connection, user_id, raw):
    now = int(time.time())
    pairing = connection.execute('''SELECT p.*,w.name AS workspace_name FROM device_pairings p
        JOIN workspaces w ON w.id=p.workspace_id WHERE p.token_hash=? AND p.user_id=?
        AND p.used_at IS NULL AND p.revoked_at IS NULL AND p.expires_at>?''', (token_hash(raw), user_id, now)).fetchone()
    if not pairing:
        raise PlatformError('Token pairing tidak valid, bukan milik akun Anda, atau kedaluwarsa.', 404)
    member = eligible(connection, pairing['workspace_id'], user_id, pairing['session_id'])
    if member['role'] != pairing['role_at_request']:
        raise PlatformError('Role berubah; buat permintaan pairing baru.', 403)
    return pairing


def approve_pairing(connection, user_id, approver_session_id, raw):
    with transaction(connection):
        live_session(connection, approver_session_id, user_id)
        pairing = inspect_pairing(connection, user_id, raw)
        now = int(time.time())
        total = connection.execute('''SELECT count(*) FROM browser_devices d JOIN account_sessions s ON s.id=d.session_id
            WHERE d.workspace_id=? AND d.user_id=? AND d.revoked_at IS NULL AND s.revoked_at IS NULL
            AND s.expires_at>? AND s.last_seen_at>?''', (pairing['workspace_id'], user_id, now, now-1800)).fetchone()[0]
        if total >= 10:
            raise PlatformError('Batas pilot 10 sesi browser aktif per akun/workspace. Cabut sesi lama.', 409)
        # A browser can approve only its own account, never assign a different owner/workspace.
        device_id = new_id()
        connection.execute('INSERT INTO browser_devices VALUES (?,?,?,?,?,?,?,?)',
            (device_id, pairing['workspace_id'], user_id, pairing['session_id'], pairing['name'], pairing['role_at_request'], now, None))
        connection.execute('UPDATE device_pairings SET used_at=? WHERE id=?', (now, pairing['id']))
        audit(connection, user_id, 'browser.paired', pairing['workspace_id'], device_id)
        return pairing['workspace_id'], device_id


def current_device(connection, workspace_id, user_id, session_id):
    member = workspaces.access(connection, workspace_id, user_id)
    live_session(connection, session_id, user_id)
    row = connection.execute('''SELECT * FROM browser_devices WHERE workspace_id=? AND user_id=?
        AND session_id=? AND revoked_at IS NULL AND role_at_pairing=?''', (workspace_id, user_id, session_id, member['role'])).fetchone()
    return row


def device_status(connection, workspace_id, user_id, session_id):
    device = current_device(connection, workspace_id, user_id, session_id)
    if not device:
        return {'device': None, 'grants': [], 'unavailable': list(UNAVAILABLE), 'policy_version': POLICY_VERSION, 'server_time': int(time.time())}
    now = int(time.time())
    grants = connection.execute('''SELECT capability,expires_at FROM preview_consents
        WHERE device_id=? AND revoked_at IS NULL AND expires_at>?''', (device['id'], now)).fetchall()
    readiness = connection.execute('SELECT secure_context,media_supported,camera,microphone,updated_at FROM browser_readiness WHERE device_id=?', (device['id'],)).fetchone()
    return {'device': {'id': device['id'], 'name': device['name'], 'created_at': device['created_at']},
            'grants': [dict(row) for row in grants], 'readiness': dict(readiness) if readiness else None,
            'unavailable': list(UNAVAILABLE), 'policy_version': POLICY_VERSION, 'server_time': now}


def grant_preview(connection, workspace_id, device_id, user_id, session_id, capability, policy, acknowledged):
    if not isinstance(capability, str) or capability not in PREVIEW_CAPABILITIES:
        raise PlatformError('Kapabilitas belum tersedia. Tidak ada izin AI/remote yang diberikan.', 403)
    if policy != POLICY_VERSION or acknowledged is not True:
        raise PlatformError('Persetujuan eksplisit untuk kebijakan preview saat ini wajib diberikan.', 400)
    with transaction(connection):
        own_device(connection, workspace_id, device_id, user_id, session_id)
        source_session = live_session(connection, session_id, user_id)
        now = int(time.time()); expires = min(now + PREVIEW_TTL, source_session['expires_at'])
        connection.execute('UPDATE preview_consents SET revoked_at=? WHERE device_id=? AND capability=? AND revoked_at IS NULL', (now, device_id, capability))
        connection.execute('INSERT INTO preview_consents VALUES (?,?,?,?,?,?,?)', (new_id(), device_id, capability, policy, now, expires, None))
        audit(connection, user_id, 'preview.consent_granted', workspace_id, device_id, capability=capability, policy=policy)
        return {'capability': capability, 'expires_at': expires, 'server_time': now}


def revoke_preview(connection, workspace_id, device_id, user_id, session_id, capability=None):
    if capability is not None and (not isinstance(capability, str) or capability not in PREVIEW_CAPABILITIES):
        raise PlatformError('Kapabilitas tidak valid.')
    with transaction(connection):
        # Revocation is idempotent even after pairing revoked; no new permissions given.
        workspaces.access(connection, workspace_id, user_id)
        device = connection.execute('''SELECT id FROM browser_devices WHERE id=? AND workspace_id=? AND user_id=? AND session_id=?''', (device_id, workspace_id, user_id, session_id)).fetchone()
        if not device:
            raise PlatformError('Pairing browser tidak ditemukan.', 404)
        now = int(time.time())
        changed = connection.execute('''UPDATE preview_consents SET revoked_at=? WHERE device_id=? AND revoked_at IS NULL
            AND (? IS NULL OR capability=?)''', (now, device_id, capability, capability)).rowcount
        if changed:
            audit(connection, user_id, 'preview.consent_revoked', workspace_id, device_id, capability=capability or 'all')


def save_readiness(connection, workspace_id, device_id, user_id, session_id, value):
    # Self-reported diagnostics only. Never accept device labels, hardware IDs, raw UA, media, AI scores.
    allowed = {'secure_context', 'media_supported', 'camera', 'microphone'}
    if not isinstance(value, dict) or set(value) != allowed:
        raise PlatformError('Readiness hanya menerima status kapabilitas yang diizinkan.')
    statuses = ('unknown', 'available', 'denied', 'unavailable')
    if type(value['secure_context']) is not bool or type(value['media_supported']) is not bool or any(not isinstance(value[k], str) or value[k] not in statuses for k in ('camera', 'microphone')):
        raise PlatformError('Status readiness tidak valid.')
    with transaction(connection):
        own_device(connection, workspace_id, device_id, user_id, session_id)
        connection.execute('''INSERT INTO browser_readiness VALUES (?,?,?,?,?,?) ON CONFLICT(device_id)
            DO UPDATE SET secure_context=excluded.secure_context,media_supported=excluded.media_supported,
            camera=excluded.camera,microphone=excluded.microphone,updated_at=excluded.updated_at''',
            (device_id, int(value['secure_context']), int(value['media_supported']), value['camera'], value['microphone'], int(time.time())))


def list_devices(connection, workspace_id, user_id, session_id):
    member = workspaces.access(connection, workspace_id, user_id)
    manage = member['role'] in ('owner', 'admin')
    now = int(time.time())
    rows = connection.execute('''SELECT d.id,d.name,d.user_id,u.display_name AS owner_name,d.created_at,d.revoked_at,
        d.session_id=? AS this_browser,
        CASE WHEN d.revoked_at IS NULL AND s.revoked_at IS NULL AND s.expires_at>? AND s.last_seen_at>?
          AND m.role=d.role_at_pairing AND u.disabled_at IS NULL THEN 'paired' ELSE 'inactive' END AS state
        FROM browser_devices d JOIN users u ON u.id=d.user_id JOIN account_sessions s ON s.id=d.session_id
        LEFT JOIN memberships m ON m.workspace_id=d.workspace_id AND m.user_id=d.user_id
        WHERE d.workspace_id=? AND (? OR d.user_id=?) ORDER BY d.created_at DESC,d.rowid DESC LIMIT 50''',
        (session_id, now, now-1800, workspace_id, int(manage), user_id)).fetchall()
    return [dict(row) for row in rows]


def revoke_device(connection, workspace_id, device_id, user_id):
    with transaction(connection):
        member = workspaces.access(connection, workspace_id, user_id)
        device = connection.execute('SELECT * FROM browser_devices WHERE id=? AND workspace_id=?', (device_id, workspace_id)).fetchone()
        if not device or device['user_id'] != user_id and member['role'] not in ('owner', 'admin'):
            raise PlatformError('Pairing browser tidak ditemukan.', 404)
        changed = connection.execute('UPDATE browser_devices SET revoked_at=? WHERE id=? AND workspace_id=? AND revoked_at IS NULL', (int(time.time()), device_id, workspace_id)).rowcount
        if changed:
            audit(connection, user_id, 'browser.pairing_revoked', workspace_id, device_id)
