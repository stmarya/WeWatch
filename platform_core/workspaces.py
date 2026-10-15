"""Tenant-scoped operations. Every write rechecks membership inside its transaction."""
import time
from platform_core.security import PlatformError, ROLE_PERMISSIONS, can_invite, can_manage_member, opaque_token, token_hash
from platform_core.store import audit, new_id, transaction


def access(connection, workspace_id, user_id, permission='workspace:read'):
    workspace = connection.execute('''SELECT w.*,m.role FROM workspaces w JOIN memberships m
        ON m.workspace_id=w.id JOIN users u ON u.id=m.user_id
        WHERE w.id=? AND m.user_id=? AND u.disabled_at IS NULL AND u.email_verified_at IS NOT NULL''', (workspace_id, user_id)).fetchone()
    if not workspace:
        raise PlatformError('Workspace tidak ditemukan.', 404)
    if permission not in ROLE_PERMISSIONS[workspace['role']]:
        raise PlatformError('Anda tidak memiliki izin untuk tindakan ini.', 403)
    return workspace


def list_workspaces(connection, user_id):
    return connection.execute('''SELECT w.id,w.name,m.role,w.created_at FROM workspaces w
        JOIN memberships m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.created_at,w.id''', (user_id,)).fetchall()


def create_workspace(connection, user_id, name):
    with transaction(connection):
        user = connection.execute('SELECT id FROM users WHERE id=? AND disabled_at IS NULL AND email_verified_at IS NOT NULL', (user_id,)).fetchone()
        if not user:
            raise PlatformError('Akun terverifikasi diperlukan.', 403)
        total = connection.execute('SELECT count(*) FROM workspaces WHERE created_by=?', (user_id,)).fetchone()[0]
        if total >= 20:
            raise PlatformError('Batas pilot: maksimal 20 workspace yang dibuat per akun.', 409)
        workspace_id = new_id()
        now = int(time.time())
        connection.execute('INSERT INTO workspaces VALUES (?,?,?,?)', (workspace_id, name, user_id, now))
        connection.execute('INSERT INTO memberships VALUES (?,?,?,?)', (workspace_id, user_id, 'owner', now))
        audit(connection, user_id, 'workspace.created', workspace_id, workspace_id)
        return workspace_id


def rename_workspace(connection, workspace_id, actor_id, name):
    with transaction(connection):
        access(connection, workspace_id, actor_id, 'workspace:settings')
        connection.execute('UPDATE workspaces SET name=? WHERE id=?', (name, workspace_id))
        audit(connection, actor_id, 'workspace.renamed', workspace_id, workspace_id)


def issue_invitation(connection, workspace_id, actor_id, email, role):
    now = int(time.time())
    with transaction(connection):
        workspace = access(connection, workspace_id, actor_id, 'members:manage')
        if not can_invite(workspace['role'], role):
            raise PlatformError('Role undangan tidak diizinkan.', 403)
        member = connection.execute('''SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.workspace_id=? AND u.email=?''', (workspace_id, email)).fetchone()
        if member:
            raise PlatformError('Akun tersebut sudah menjadi anggota.', 409)
        # Bound mail/token abuse and keep pending invitations manageable.
        total = connection.execute('''SELECT count(*) FROM invitations WHERE workspace_id=?
            AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>?''', (workspace_id, now)).fetchone()[0]
        if total >= 100:
            raise PlatformError('Batas pilot: maksimal 100 undangan aktif per workspace.', 409)
        connection.execute('''UPDATE invitations SET revoked_at=? WHERE workspace_id=? AND email=?
            AND accepted_at IS NULL AND revoked_at IS NULL''', (now, workspace_id, email))
        invitation_id = new_id()
        raw = opaque_token()
        connection.execute('INSERT INTO invitations VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (invitation_id, workspace_id, email, role, actor_id, token_hash(raw), now, now + 259200, None, None))
        audit(connection, actor_id, 'member.invited', workspace_id, invitation_id, role=role)
        return raw, workspace['name']


def accept_invitation(connection, user_id, email, raw):
    now = int(time.time())
    digest = token_hash(raw)
    with transaction(connection):
        invitation = connection.execute('''SELECT i.* FROM invitations i JOIN workspaces w ON w.id=i.workspace_id
            WHERE i.token_hash=? AND i.email=? AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>?''',
                                        (digest, email, now)).fetchone()
        if not invitation:
            raise PlatformError('Undangan tidak valid, bukan untuk akun Anda, atau sudah kedaluwarsa.')
        inviter = connection.execute('''SELECT m.role FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.workspace_id=? AND m.user_id=? AND u.disabled_at IS NULL''',
                                    (invitation['workspace_id'], invitation['invited_by'])).fetchone()
        if not inviter or not can_invite(inviter['role'], invitation['role']):
            raise PlatformError('Undangan tidak lagi diizinkan. Minta undangan baru.')
        existing = connection.execute('SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?', (invitation['workspace_id'], user_id)).fetchone()
        if existing:
            raise PlatformError('Anda sudah menjadi anggota workspace ini.', 409)
        connection.execute('INSERT INTO memberships VALUES (?,?,?,?)', (invitation['workspace_id'], user_id, invitation['role'], now))
        connection.execute('UPDATE invitations SET accepted_at=? WHERE id=?', (now, invitation['id']))
        audit(connection, user_id, 'member.invitation_accepted', invitation['workspace_id'], invitation['id'], role=invitation['role'])
        return invitation['workspace_id']


def revoke_invitation(connection, workspace_id, actor_id, invitation_id):
    with transaction(connection):
        actor = access(connection, workspace_id, actor_id, 'members:manage')
        invitation = connection.execute('SELECT * FROM invitations WHERE id=? AND workspace_id=?', (invitation_id, workspace_id)).fetchone()
        if not invitation:
            raise PlatformError('Undangan tidak ditemukan.', 404)
        if not can_invite(actor['role'], invitation['role']):
            raise PlatformError('Anda tidak dapat mengelola undangan untuk role ini.', 403)
        connection.execute('UPDATE invitations SET revoked_at=? WHERE id=? AND workspace_id=?', (int(time.time()), invitation_id, workspace_id))
        audit(connection, actor_id, 'member.invitation_revoked', workspace_id, invitation_id)


def change_member(connection, workspace_id, actor_id, member_id, new_role=None, remove=False):
    if not remove and new_role not in ('admin', 'host', 'member', 'viewer'):
        raise PlatformError('Role anggota tidak valid.')
    with transaction(connection):
        actor = access(connection, workspace_id, actor_id, 'members:manage')
        target = connection.execute('SELECT role FROM memberships WHERE workspace_id=? AND user_id=?', (workspace_id, member_id)).fetchone()
        if not target:
            raise PlatformError('Anggota tidak ditemukan.', 404)
        if not can_manage_member(actor['role'], target['role'], None if remove else new_role):
            raise PlatformError('Role ini tidak dapat diubah/dihapus. Owner harus ditransfer secara khusus.', 403)
        if member_id == actor_id:
            raise PlatformError('Gunakan alur keluar workspace untuk menghapus keanggotaan sendiri.', 409)
        if remove:
            connection.execute('DELETE FROM memberships WHERE workspace_id=? AND user_id=?', (workspace_id, member_id))
            event = 'member.removed'
        else:
            connection.execute('UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?', (new_role, workspace_id, member_id))
            event = 'member.role_changed'
        audit(connection, actor_id, event, workspace_id, member_id, role=new_role)


def leave_workspace(connection, workspace_id, user_id):
    with transaction(connection):
        actor = access(connection, workspace_id, user_id)
        if actor['role'] == 'owner':
            raise PlatformError('Transfer ownership terlebih dahulu; workspace tidak boleh tanpa owner.', 409)
        connection.execute('DELETE FROM memberships WHERE workspace_id=? AND user_id=?', (workspace_id, user_id))
        audit(connection, user_id, 'member.left', workspace_id, user_id)


def transfer_ownership(connection, workspace_id, actor_id, target_id, password):
    from werkzeug.security import check_password_hash
    # Reauthentication is hashed outside the SQLite write lock.
    user = connection.execute('SELECT password_hash FROM users WHERE id=?', (actor_id,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        raise PlatformError('Password konfirmasi tidak valid.', 403)
    with transaction(connection):
        access(connection, workspace_id, actor_id, 'ownership:transfer')
        current = connection.execute('SELECT password_hash,disabled_at FROM users WHERE id=?', (actor_id,)).fetchone()
        if current['password_hash'] != user['password_hash'] or current['disabled_at'] is not None:
            raise PlatformError('Akun berubah; masuk dan konfirmasi ulang.', 403)
        target = connection.execute('''SELECT m.role FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.workspace_id=? AND m.user_id=? AND u.email_verified_at IS NOT NULL AND u.disabled_at IS NULL''', (workspace_id, target_id)).fetchone()
        if not target or target_id == actor_id:
            raise PlatformError('Pilih anggota aktif lain yang sudah terverifikasi.')
        connection.execute("UPDATE memberships SET role='admin' WHERE workspace_id=? AND user_id=?", (workspace_id, actor_id))
        connection.execute("UPDATE memberships SET role='owner' WHERE workspace_id=? AND user_id=?", (workspace_id, target_id))
        audit(connection, actor_id, 'workspace.ownership_transferred', workspace_id, target_id)
