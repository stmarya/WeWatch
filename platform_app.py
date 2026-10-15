"""WeWatch isolated control plane + browser onboarding. No camera/OS/media imports."""
from datetime import datetime, timedelta, timezone
from functools import wraps
import hmac
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from platform_core import accounts, workspaces
from platform_core.mail import Mailer, MailDeliveryError
from platform_core.security import PlatformError, ROLE_PERMISSIONS, bounded_name, email_address, password_value
from platform_core.store import Store
from utils.security import SlidingWindowRateLimiter

ROOT = Path(__file__).resolve().parent


def create_app(config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__, template_folder='platform_templates', static_folder='platform_static', static_url_path='/assets')
    environment = os.getenv('PLATFORM_ENV', 'development')
    app.config.update(
        SECRET_KEY=os.getenv('PLATFORM_SESSION_SECRET', ''),
        DATABASE=os.getenv('PLATFORM_DATABASE_PATH') or str(ROOT / 'instance' / 'platform' / 'platform.sqlite3'),
        ENVIRONMENT=environment,
        PUBLIC_URL=os.getenv('PLATFORM_PUBLIC_URL', 'http://127.0.0.1:5002').rstrip('/'),
        MAIL_TRANSPORT=os.getenv('PLATFORM_MAIL_TRANSPORT', 'disabled'),
        MAIL_DIRECTORY=os.getenv('PLATFORM_MAIL_DIRECTORY') or str(ROOT / 'instance' / 'platform' / 'outbox'),
        MAIL_FROM=os.getenv('PLATFORM_MAIL_FROM', 'no-reply@wewatch.example'),
        SMTP_HOST=os.getenv('PLATFORM_SMTP_HOST', ''), SMTP_PORT=int(os.getenv('PLATFORM_SMTP_PORT') or '587'),
        SMTP_USER=os.getenv('PLATFORM_SMTP_USER', ''), SMTP_PASSWORD=os.getenv('PLATFORM_SMTP_PASSWORD', ''),
        SESSION_COOKIE_NAME='wewatch_platform', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=environment == 'production',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=65536,
        RATE_LIMITS_ENABLED=True,
    )
    if config:
        app.config.update(config)
    secret = app.config['SECRET_KEY']
    if not isinstance(secret, str) or len(secret) < 32 or len(set(secret)) < 8:
        raise ValueError('Set PLATFORM_SESSION_SECRET to a distinct secret of at least 32 characters')
    if app.config['ENVIRONMENT'] not in ('development', 'production'):
        raise ValueError('Unsupported PLATFORM_ENV')
    public = urlsplit(app.config['PUBLIC_URL'])
    if (public.scheme not in ('http', 'https') or not public.hostname or public.username
            or public.password or public.path or public.query or public.fragment):
        raise ValueError('PLATFORM_PUBLIC_URL must be a trusted origin without a path or credentials')
    if app.config['ENVIRONMENT'] == 'production':
        if public.scheme != 'https' or not app.config['SESSION_COOKIE_SECURE'] or app.config['MAIL_TRANSPORT'] != 'smtp' or not app.config['SMTP_HOST']:
            raise ValueError('Production requires HTTPS, secure cookies and SMTP mail delivery')
    elif public.scheme == 'http' and public.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Plain HTTP is only permitted for loopback development')
    email_address(app.config['MAIL_FROM'])
    app.config['TRUSTED_HOSTS'] = [public.hostname]
    if app.config['ENVIRONMENT'] == 'development':
        app.config['TRUSTED_HOSTS'] += ['localhost', '127.0.0.1']
    store = Store(app.config['DATABASE'])
    app.extensions['platform_store'] = store
    mailer = app.config.get('TEST_MAILER') if app.testing else None
    app.extensions['platform_mailer'] = mailer or Mailer(app.config)
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt:32768:8:1')
    limiters = {
        'login': SlidingWindowRateLimiter(15, 900), 'register': SlidingWindowRateLimiter(6, 900),
        'mail': SlidingWindowRateLimiter(6, 900), 'write': SlidingWindowRateLimiter(100, 60),
    }

    def database():
        if 'platform_db' not in g:
            g.platform_db = store.connect()
        return g.platform_db

    @app.teardown_appcontext
    def close_database(_error):
        connection = g.pop('platform_db', None)
        if connection is not None:
            connection.close()

    def api_request():
        return request.path.startswith('/api/') or request.is_json

    def data():
        if request.is_json:
            value = request.get_json(silent=True)
            if not isinstance(value, dict):
                raise PlatformError('JSON object wajib diisi.')
            return value
        return request.form

    def rate_limit(kind):
        if app.config['RATE_LIMITS_ENABLED'] and not limiters[kind].allow(request.remote_addr or 'unknown'):
            raise PlatformError('Terlalu banyak percobaan. Coba lagi nanti.', 429)

    def authenticated(handler):
        @wraps(handler)
        def protected(*args, **kwargs):
            if g.user is None:
                if api_request():
                    raise PlatformError('Login diperlukan.', 401)
                return redirect(url_for('login'))
            if g.user['email_verified_at'] is None:
                raise PlatformError('Verifikasi email diperlukan.', 403)
            return handler(*args, **kwargs)
        return protected

    def complete(message, endpoint='dashboard', **values):
        if api_request():
            return jsonify(success=True, message=message, **values)
        flash(message, 'success')
        return redirect(url_for(endpoint, **values))

    def send_account_mail(email, raw, purpose):
        if raw is not None:
            route = '/verify-email' if purpose == 'verify' else '/password/reset'
            label = 'Verifikasi akun' if purpose == 'verify' else 'Reset password'
            app.extensions['platform_mailer'].send(email, 'WeWatch — ' + label,
                f'{label} WeWatch melalui tautan berikut:\n{app.config["PUBLIC_URL"]}{route}#token={raw}\n\n'
                'Token hanya dapat digunakan sekali. Abaikan jika Anda tidak meminta tindakan ini.\n'
                'Anda juga dapat menempelkan token secara manual pada halaman tersebut.\n')

    def require_mail():
        if not app.extensions['platform_mailer'].ready:
            raise MailDeliveryError('Mail delivery is not configured')

    @app.before_request
    def request_boundary():
        g.user = None
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        if request.endpoint != 'static':
            raw = session.get('account_session')
            if raw:
                g.user = accounts.session_user(database(), raw)
                if g.user is None:
                    session.clear()
                    session['csrf_token'] = secrets.token_urlsafe(32)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            # Chromium may send Origin:null on form navigation under
            # Referrer-Policy:no-referrer. Only same-origin browser navigation
            # may use that value; the CSRF token remains mandatory below.
            if origin == 'null':
                if request.headers.get('Sec-Fetch-Site') != 'same-origin':
                    raise PlatformError('Origin tidak diizinkan.', 403)
            elif origin and origin != app.config['PUBLIC_URL'] and origin != request.host_url.rstrip('/'):
                raise PlatformError('Origin tidak diizinkan.', 403)
            supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            expected = session.get('csrf_token', '')
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
                raise PlatformError('CSRF token tidak valid. Muat ulang halaman.', 403)
            rate_limit('write')

    @app.after_request
    def secure_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = ('camera=(self), microphone=(self), geolocation=(), payment=()'
            if request.endpoint == 'onboarding.page' and g.get('onboarding_media_allowed', False) else 'camera=(), microphone=(), geolocation=(), payment=()')
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.is_secure or app.config['ENVIRONMENT'] == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.template_filter('time_label')
    def time_label(value):
        return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %Y · %H:%M UTC')

    @app.context_processor
    def template_context():
        return {'current_user': g.get('user'), 'csrf_token': session.get('csrf_token', '')}

    @app.errorhandler(PlatformError)
    def expected_error(error):
        if api_request():
            return jsonify(error=str(error)), error.status
        return render_template('error.html', message=str(error), status=error.status), error.status

    @app.errorhandler(MailDeliveryError)
    def mail_error(_error):
        logging.warning('Platform mail delivery unavailable; no recipient/token is logged')
        return expected_error(PlatformError('Pengiriman email belum tersedia. Hubungi operator atau coba lagi nanti.', 503))

    @app.errorhandler(404)
    def not_found(_error):
        return expected_error(PlatformError('Halaman tidak ditemukan.', 404))

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        logging.error('Platform database operation failed (%s)', type(error).__name__)
        return expected_error(PlatformError('Layanan sementara tidak tersedia. Coba lagi nanti.', 503))

    @app.get('/healthz')
    def health():
        return jsonify(status='ok', service='wewatch-platform')

    @app.get('/readyz')
    def ready():
        database().execute('SELECT 1')
        ready_mail = app.extensions['platform_mailer'].ready
        return jsonify(status='ready' if ready_mail else 'not_ready', email_delivery=ready_mail), 200 if ready_mail else 503

    @app.get('/')
    def landing():
        return redirect(url_for('dashboard' if g.user else 'login'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'GET':
            return render_template('auth.html', mode='register')
        rate_limit('register')
        require_mail()
        value = data()
        email = email_address(value.get('email'))
        password = password_value(value.get('password'))
        name = bounded_name(value.get('display_name'), default='Pengguna')
        raw = accounts.register(database(), email, password, name)
        send_account_mail(email, raw, 'verify')
        return complete('Jika pendaftaran memenuhi syarat, email verifikasi akan dikirim. Jika sudah memiliki akun, login atau minta ulang verifikasi.', 'login')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'GET':
            return render_template('auth.html', mode='login')
        rate_limit('login')
        value = data()
        email = email_address(value.get('email'))
        password = value.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise PlatformError('Email atau password tidak valid.', 401)
        raw = accounts.authenticate(database(), email, password, dummy_hash)
        session.clear()
        session['account_session'] = raw
        session['csrf_token'] = secrets.token_urlsafe(32)
        session.permanent = True
        return complete('Berhasil masuk.')

    @app.post('/logout')
    @authenticated
    def logout():
        accounts.revoke_sessions(database(), g.user['id'], g.user['session_id'])
        session.clear()
        return complete('Anda sudah keluar.', 'login')

    @app.post('/account/logout-all')
    @authenticated
    def logout_all():
        accounts.revoke_sessions(database(), g.user['id'])
        session.clear()
        return complete('Semua sesi akun sudah dicabut.', 'login')

    @app.route('/verify-email', methods=['GET', 'POST'])
    def verify_email():
        if request.method == 'GET':
            return render_template('auth.html', mode='verify')
        rate_limit('mail')
        accounts.consume_account_token(database(), data().get('token'), 'verify')
        return complete('Email terverifikasi. Silakan login.', 'login')

    @app.route('/verification/resend', methods=['GET', 'POST'])
    def resend_verification():
        if request.method == 'GET':
            return render_template('auth.html', mode='resend')
        rate_limit('mail'); require_mail()
        email = email_address(data().get('email'))
        send_account_mail(email, accounts.request_token(database(), email, 'verify'), 'verify')
        return complete('Jika akun memerlukan verifikasi, email akan dikirim.', 'login')

    @app.route('/password/forgot', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'GET':
            return render_template('auth.html', mode='forgot')
        rate_limit('mail'); require_mail()
        email = email_address(data().get('email'))
        send_account_mail(email, accounts.request_token(database(), email, 'reset'), 'reset')
        return complete('Jika akun memenuhi syarat, email reset password akan dikirim.', 'login')

    @app.route('/password/reset', methods=['GET', 'POST'])
    def reset_password():
        if request.method == 'GET':
            return render_template('auth.html', mode='reset')
        rate_limit('mail')
        value = data()
        accounts.consume_account_token(database(), value.get('token'), 'reset', password_value(value.get('password')))
        session.clear()
        return complete('Password diperbarui dan seluruh sesi lama dicabut. Silakan login.', 'login')

    @app.get('/app')
    @authenticated
    def dashboard():
        return render_template('dashboard.html', workspaces=workspaces.list_workspaces(database(), g.user['id']))

    @app.get('/api/me')
    @authenticated
    def me():
        return jsonify(user={'id': g.user['id'], 'email': g.user['email'], 'display_name': g.user['display_name'], 'email_verified': True},
                       workspaces=[dict(row) for row in workspaces.list_workspaces(database(), g.user['id'])])

    @app.get('/api/session')
    def csrf_session():
        return jsonify(csrf_token=session['csrf_token'], authenticated=g.user is not None)

    @app.post('/workspaces')
    @authenticated
    def create_workspace():
        workspace_id = workspaces.create_workspace(database(), g.user['id'], bounded_name(data().get('name')))
        return complete('Workspace dibuat.', 'workspace_page', workspace_id=workspace_id)

    @app.get('/workspaces/<workspace_id>')
    @authenticated
    def workspace_page(workspace_id):
        workspace = workspaces.access(database(), workspace_id, g.user['id'])
        can_manage = workspace['role'] in ('owner', 'admin')
        members = database().execute('''SELECT u.id,u.email,u.display_name,m.role FROM memberships m
            JOIN users u ON u.id=m.user_id WHERE m.workspace_id=? ORDER BY m.created_at,u.id''', (workspace_id,)).fetchall() if can_manage else []
        invitations = database().execute('''SELECT id,email,role,expires_at FROM invitations WHERE workspace_id=?
            AND revoked_at IS NULL AND accepted_at IS NULL AND expires_at>? ORDER BY created_at DESC''', (workspace_id, int(time.time()))).fetchall() if can_manage else []
        events = database().execute('''SELECT a.event,a.resource_id,a.metadata,a.created_at,u.display_name AS actor_name
            FROM audit_events a LEFT JOIN users u ON u.id=a.actor_id WHERE a.workspace_id=?
            ORDER BY a.created_at DESC,a.rowid DESC LIMIT 30''', (workspace_id,)).fetchall() if can_manage else []
        return render_template('workspace.html', workspace=workspace, members=members, invitations=invitations,
                               events=events, can_manage=can_manage, permissions=ROLE_PERMISSIONS[workspace['role']])

    @app.get('/api/workspaces/<workspace_id>')
    @authenticated
    def workspace_api(workspace_id):
        workspace = workspaces.access(database(), workspace_id, g.user['id'])
        return jsonify(workspace={'id': workspace['id'], 'name': workspace['name'], 'role': workspace['role']}, permissions=ROLE_PERMISSIONS[workspace['role']])

    @app.get('/api/workspaces/<workspace_id>/audit')
    @authenticated
    def workspace_audit(workspace_id):
        workspaces.access(database(), workspace_id, g.user['id'], 'audit:read')
        rows = database().execute('''SELECT id,event,actor_id,resource_id,metadata,created_at FROM audit_events
            WHERE workspace_id=? ORDER BY created_at DESC,rowid DESC LIMIT 50''', (workspace_id,)).fetchall()
        return jsonify(events=[dict(row) for row in rows])

    @app.post('/workspaces/<workspace_id>/settings')
    @authenticated
    def workspace_settings(workspace_id):
        workspaces.rename_workspace(database(), workspace_id, g.user['id'], bounded_name(data().get('name')))
        return complete('Pengaturan disimpan.', 'workspace_page', workspace_id=workspace_id)

    @app.post('/workspaces/<workspace_id>/invitations')
    @authenticated
    def invite_member(workspace_id):
        workspaces.access(database(), workspace_id, g.user['id'], 'members:manage')
        require_mail(); rate_limit('mail')
        value = data(); email = email_address(value.get('email'))
        raw, name = workspaces.issue_invitation(database(), workspace_id, g.user['id'], email, value.get('role', 'member'))
        app.extensions['platform_mailer'].send(email, 'WeWatch — Undangan workspace',
            f'Anda diundang ke workspace {name}.\nDaftar/verifikasi akun dan login dengan alamat email undangan, lalu buka:\n'
            f'{app.config["PUBLIC_URL"]}/invitations/accept#token={raw}\n\nUndangan berlaku 72 jam dan hanya dapat digunakan sekali.')
        return complete('Undangan dikirim melalui email.', 'workspace_page', workspace_id=workspace_id)

    @app.post('/workspaces/<workspace_id>/invitations/<invitation_id>/revoke')
    @authenticated
    def revoke_invite(workspace_id, invitation_id):
        workspaces.revoke_invitation(database(), workspace_id, g.user['id'], invitation_id)
        return complete('Undangan dicabut.', 'workspace_page', workspace_id=workspace_id)

    @app.route('/invitations/accept', methods=['GET', 'POST'])
    def invitation_accept():
        if request.method == 'GET':
            return render_template('auth.html', mode='invite')
        if not g.user:
            raise PlatformError('Login dengan akun terverifikasi yang menerima undangan terlebih dahulu.', 401)
        if g.user['email_verified_at'] is None:
            raise PlatformError('Verifikasi email diperlukan.', 403)
        workspace_id = workspaces.accept_invitation(database(), g.user['id'], g.user['email'], data().get('token'))
        return complete('Anda bergabung ke workspace.', 'workspace_page', workspace_id=workspace_id)

    @app.post('/workspaces/<workspace_id>/members/<member_id>/role')
    @authenticated
    def member_role(workspace_id, member_id):
        workspaces.change_member(database(), workspace_id, g.user['id'], member_id, data().get('role'))
        return complete('Role anggota diperbarui.', 'workspace_page', workspace_id=workspace_id)

    @app.post('/workspaces/<workspace_id>/members/<member_id>/remove')
    @authenticated
    def member_remove(workspace_id, member_id):
        workspaces.change_member(database(), workspace_id, g.user['id'], member_id, remove=True)
        return complete('Anggota dihapus.', 'workspace_page', workspace_id=workspace_id)

    @app.post('/workspaces/<workspace_id>/leave')
    @authenticated
    def leave(workspace_id):
        workspaces.leave_workspace(database(), workspace_id, g.user['id'])
        return complete('Anda keluar dari workspace.')

    @app.post('/workspaces/<workspace_id>/ownership')
    @authenticated
    def ownership(workspace_id):
        value = data()
        if not isinstance(value.get('member_id'), str) or not isinstance(value.get('password'), str) or len(value['password']) > 128:
            raise PlatformError('Anggota dan password konfirmasi wajib diisi.')
        workspaces.transfer_ownership(database(), workspace_id, g.user['id'], value['member_id'], value['password'])
        return complete('Ownership ditransfer; role Anda sekarang Admin.', 'workspace_page', workspace_id=workspace_id)

    @app.cli.command('check-platform')
    def check_platform():
        import click
        click.echo('Database schema ready; mail configured: ' + str(app.extensions['platform_mailer'].ready))
        click.echo('Isolated control plane + session-bound local browser preview. AI/meeting/desktop grants remain unavailable.')

    from platform_core.onboarding_routes import register_onboarding
    register_onboarding(app, database, data, authenticated, complete)
    return app


if __name__ == '__main__':
    application = create_app()
    application.run(host='127.0.0.1', port=int(os.getenv('PLATFORM_PORT', '5002')), debug=False, use_reloader=False)
