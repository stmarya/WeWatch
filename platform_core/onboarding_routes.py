"""Web routes for the isolated browser onboarding pilot."""
import time
from flask import Blueprint, g, jsonify, render_template
from platform_core import devices, workspaces
from platform_core.security import PlatformError
from platform_core.store import audit, transaction


def register_onboarding(app, database, data, authenticated, complete):
    bp = Blueprint('onboarding', __name__)

    @bp.get('/workspaces/<workspace_id>/onboarding')
    @authenticated
    def page(workspace_id):
        workspace = workspaces.access(database(), workspace_id, g.user['id'])
        g.onboarding_media_allowed = workspace['role'] != 'viewer'
        status = devices.device_status(database(), workspace_id, g.user['id'], g.user['session_id'])
        return render_template('onboarding.html', workspace=workspace, status=status,
            enrolled=devices.list_devices(database(), workspace_id, g.user['id'], g.user['session_id']))

    @bp.post('/workspaces/<workspace_id>/pairing')
    @authenticated
    def begin(workspace_id):
        result = devices.begin_pairing(database(), workspace_id, g.user['id'], g.user['session_id'], data().get('name'))
        return jsonify(pairing=result), 201

    @bp.post('/workspaces/<workspace_id>/pairing/<pairing_id>/cancel')
    @authenticated
    def cancel(workspace_id, pairing_id):
        with transaction(database()):
            workspaces.access(database(), workspace_id, g.user['id'])
            row = database().execute('''SELECT id FROM device_pairings WHERE id=? AND workspace_id=?
                AND user_id=? AND session_id=?''', (pairing_id, workspace_id, g.user['id'], g.user['session_id'])).fetchone()
            if not row:
                raise PlatformError('Permintaan pairing tidak ditemukan.', 404)
            database().execute('UPDATE device_pairings SET revoked_at=? WHERE id=? AND revoked_at IS NULL', (int(time.time()), pairing_id))
            audit(database(), g.user['id'], 'browser.pairing_cancelled', workspace_id, pairing_id)
        return jsonify(success=True)

    @bp.get('/device-pairing')
    @authenticated
    def pairing_page():
        return render_template('pairing.html')

    @bp.post('/device-pairing/inspect')
    @authenticated
    def inspect():
        row = devices.inspect_pairing(database(), g.user['id'], data().get('token'))
        return jsonify(pairing={'name': row['name'], 'workspace_name': row['workspace_name'], 'expires_at': row['expires_at']})

    @bp.post('/device-pairing/approve')
    @authenticated
    def approve():
        value = data()
        if value.get('acknowledged') is not True:
            raise PlatformError('Konfirmasikan sesi browser dan workspace sebelum pairing.')
        workspace_id, _device_id = devices.approve_pairing(database(), g.user['id'], g.user['session_id'], value.get('token'))
        return jsonify(success=True, workspace_id=workspace_id,
                       message='Pairing disetujui. Kembali ke browser peminta; tidak ada izin media/remote otomatis.')

    @bp.get('/api/workspaces/<workspace_id>/onboarding')
    @authenticated
    def status(workspace_id):
        return jsonify(devices.device_status(database(), workspace_id, g.user['id'], g.user['session_id']))

    @bp.post('/workspaces/<workspace_id>/devices/<device_id>/readiness')
    @authenticated
    def readiness(workspace_id, device_id):
        devices.save_readiness(database(), workspace_id, device_id, g.user['id'], g.user['session_id'], data())
        return jsonify(success=True)

    @bp.post('/workspaces/<workspace_id>/devices/<device_id>/consents')
    @authenticated
    def grant(workspace_id, device_id):
        value = data()
        result = devices.grant_preview(database(), workspace_id, device_id, g.user['id'], g.user['session_id'],
            value.get('capability'), value.get('policy_version'), value.get('acknowledged'))
        return jsonify(grant=result)

    @bp.post('/workspaces/<workspace_id>/devices/<device_id>/consents/revoke')
    @authenticated
    def stop(workspace_id, device_id):
        devices.revoke_preview(database(), workspace_id, device_id, g.user['id'], g.user['session_id'], data().get('capability'))
        return jsonify(success=True)

    @bp.post('/workspaces/<workspace_id>/devices/<device_id>/revoke')
    @authenticated
    def revoke(workspace_id, device_id):
        devices.revoke_device(database(), workspace_id, device_id, g.user['id'])
        return complete('Pairing dicabut. Preview pada browser terkait akan dihentikan saat pemeriksaan berikutnya.', 'onboarding.page', workspace_id=workspace_id)

    app.register_blueprint(bp)
