import os
import glob
import sqlite3
import time
import logging
import uuid
import hmac
import secrets
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from flask import (
    Flask, render_template, Response, request, jsonify, redirect, session, url_for, flash,
    get_flashed_messages, send_file,
)
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Starting The Ultimate Watcher Server...")

# Load Env
load_dotenv()

from camera import AICamera, FEATURES, STATUS
from services.jarvis import start_jarvis
from services.database import init_db, init_attendance_db
from services.room_auth import issue_room_token
from services import mailer
from services.avatar_uploads import (
    MAX_UPLOAD_BYTES, AvatarUploadError, delete_avatar_upload, save_avatar_upload, uploaded_file_path,
)
from services.avatars import grouped_avatars, is_valid_avatar, upload_id
from services.user_store import (
    BIO_MAX_LENGTH, DuplicateEmailError, InvalidCurrentPasswordError, InvalidTokenError, UserStore,
    validate_registration,
)
from utils.security import make_rate_limiter, safe_face_name

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv(
    'WEBWATCH_SESSION_SECRET',
    os.getenv('WEBRTC_SECRET_KEY', os.urandom(32).hex()),
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('WEBWATCH_COOKIE_SECURE', 'false').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
# Hard request cap; avatar uploads are additionally limited to 2 MB.
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES + 512 * 1024

BASE_DIR = Path(__file__).resolve().parent
GALLERY_FOLDER = str(BASE_DIR / 'static' / 'gallery')
ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()
# PostgreSQL (shared, multi-replica) when WEBWATCH_DATABASE_URL is set; SQLite otherwise.
USERS_DB = os.getenv('WEBWATCH_DATABASE_URL', '').strip()
if not USERS_DB:
    USERS_DB = Path(os.getenv('WEBWATCH_USERS_DB', 'users.db'))
    if not USERS_DB.is_absolute():
        USERS_DB = BASE_DIR / USERS_DB
REQUIRE_EMAIL_VERIFICATION = os.getenv('WEBWATCH_REQUIRE_EMAIL_VERIFICATION', 'false').lower() == 'true'
PUBLIC_URL = os.getenv('WEBWATCH_PUBLIC_URL', '').strip().rstrip('/')
WEBRTC_CLIENT_URL = os.getenv('WEBRTC_CLIENT_URL', 'http://localhost:5001/').strip()
WEBRTC_ROOM_NAME = os.getenv('WEBRTC_ROOM_NAME', 'gmeet_room')
os.makedirs(GALLERY_FOLDER, exist_ok=True)
user_store = UserStore(USERS_DB)

init_db()
init_attendance_db()

# Initialize Camera with AI processing in background
camera = AICamera(FEATURES, STATUS)
# Auth limiters are shared across replicas through Redis when REDIS_URL is set.
_RATE_LIMIT_REDIS = os.getenv('WEBWATCH_RATE_LIMIT_REDIS_URL', os.getenv('REDIS_URL', '')).strip() or None
login_limiter = make_rate_limiter('login', 8, 60, _RATE_LIMIT_REDIS)
registration_limiter = make_rate_limiter('register', 5, 600, _RATE_LIMIT_REDIS)
# Email/password changes require the current password; throttle guessing per account.
account_security_limiter = make_rate_limiter('account-security', 10, 600, _RATE_LIMIT_REDIS)
email_limiter = make_rate_limiter('email-send', 5, 900, _RATE_LIMIT_REDIS)
upload_limiter = make_rate_limiter('avatar-upload', 10, 600, _RATE_LIMIT_REDIS)
face_limiter = make_rate_limiter('face', 6, 60, None)
snapshot_limiter = make_rate_limiter('snapshot', 20, 60, None)

# Mulai pendengar Jarvis di background
start_jarvis(camera)

def _preauth_csrf_token():
    token = session.get('preauth_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['preauth_csrf_token'] = token
    return token


def _valid_csrf(expected_key='csrf_token'):
    expected = session.get(expected_key, '')
    supplied = request.headers.get('X-CSRF-Token', '') or request.form.get('csrf_token', '')
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _start_authenticated_session(**values):
    session.clear()
    session.update(values)
    session['csrf_token'] = secrets.token_urlsafe(32)
    session.permanent = True


def _start_user_session(user):
    _start_authenticated_session(
        user_id=user.id,
        user_email=user.email,
        display_name=user.display_name,
        role=user.role,
        session_epoch=user.session_epoch,
    )


def _external_url(endpoint, **values):
    """Absolute link for emails. Prefer WEBWATCH_PUBLIC_URL to avoid Host-header spoofing."""
    path = url_for(endpoint, **values)
    if PUBLIC_URL:
        return PUBLIC_URL + path
    return request.url_root.rstrip('/') + path


def _client_key():
    return request.remote_addr or 'unknown'


def _send_verification(user):
    token = user_store.issue_email_verification(user.id)
    return mailer.send_verification_email(
        user.email, user.display_name, _external_url('auth_verify_email', token=token)
    )


ACCOUNT_ENDPOINTS = {
    'account', 'account_profile', 'account_email', 'account_password', 'account_avatar_upload',
    'account_avatar_remove', 'account_resend_verification', 'account_export', 'account_delete',
    'account_meeting',
}
PUBLIC_ENDPOINTS = {
    'auth_login', 'auth_register', 'auth_forgot_password', 'auth_reset_password',
    'auth_verify_email', 'auth_confirm_email_change', 'media_avatar', 'manifest',
}
_MONTHS_ID = ('Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des')


@app.template_filter('datetime_id')
def format_datetime_id(value):
    """Render stored UTC ISO timestamps as e.g. '05 Okt 2026, 09:37 UTC'."""
    if not value:
        return '-'
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{parsed.day:02d} {_MONTHS_ID[parsed.month - 1]} {parsed.year}, {parsed:%H:%M} UTC"


@app.before_request
def require_authenticated_session():
    public_static = request.path.startswith('/static/') and not request.path.startswith('/static/gallery/')
    # Public endpoints validate their own pre-auth CSRF token on POST.
    if request.endpoint in PUBLIC_ENDPOINTS or public_static:
        return None

    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and not _valid_csrf():
        return jsonify(error='invalid csrf token'), 403

    if request.endpoint in ACCOUNT_ENDPOINTS:
        if session.get('user_id'):
            return None
        return redirect(url_for('auth_login'))

    if request.endpoint == 'auth_logout':
        if session.get('user_id') or session.get('admin_authenticated'):
            return None
        return redirect(url_for('auth_login'))

    # The camera, gallery, AI controls, and remote-control surface remain
    # admin-only. A newly registered user receives a separate account page.
    if not session.get('admin_authenticated'):
        if request.path == '/':
            return redirect(url_for('auth_login'))
        return jsonify(error='admin authentication required'), 403
    return None


@app.errorhandler(413)
def request_too_large(_error):
    if session.get('user_id') and request.endpoint == 'account_avatar_upload':
        flash('Ukuran foto maksimal 2 MB.', 'error')
        return redirect(url_for('account') + '#profileSection')
    return jsonify(error='request too large'), 413


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(self), microphone=(self), geolocation=(), payment=()',
    )
    response.headers.setdefault(
        'Content-Security-Policy',
        "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    )
    if request.is_secure:
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )
    return response



# --------------------------------------------------------------------- auth
def _render_login(error=None, status=200, notice=None):
    return render_template(
        'login.html', error=error, notice=notice, csrf_token=_preauth_csrf_token(),
        registered=request.args.get('registered') == '1',
    ), status


@app.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    if request.method == 'GET':
        return _render_login(notice=' '.join(get_flashed_messages()) or None)
    if not _valid_csrf('preauth_csrf_token'):
        return _render_login('Sesi formulir kedaluwarsa. Muat ulang halaman.', 403)
    if not login_limiter.allow(_client_key()):
        return _render_login('Terlalu banyak percobaan login. Coba lagi nanti.', 429)

    auth_method = request.form.get('auth_method', 'user')
    if auth_method == 'admin':
        supplied = (request.form.get('token') or '').strip()
        if ADMIN_TOKEN and hmac.compare_digest(supplied, ADMIN_TOKEN):
            _start_authenticated_session(admin_authenticated=True, role='admin')
            return redirect(url_for('index'))
    else:
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        user = user_store.authenticate(email, password)
        if user:
            if REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
                if email_limiter.allow(f'verify:{user.id}'):
                    _send_verification(user)
                return _render_login(
                    'Email belum diverifikasi. Kami sudah mengirim link verifikasi ke email kamu.', 403
                )
            _start_user_session(user)
            return redirect(url_for('account'))
    # Do not disclose whether an email exists or which credential failed.
    return _render_login('Email/password atau token admin tidak valid.')


@app.route('/auth/register', methods=['GET', 'POST'])
def auth_register():
    errors = {}
    values = {'display_name': '', 'email': '', 'avatar': ''}
    csrf_token = _preauth_csrf_token()
    if request.method == 'POST':
        values = {
            'display_name': (request.form.get('display_name') or '').strip(),
            'email': (request.form.get('email') or '').strip(),
            'avatar': (request.form.get('avatar') or '').strip(),
        }
        if not _valid_csrf('preauth_csrf_token'):
            errors['form'] = 'Sesi formulir kedaluwarsa. Muat ulang halaman.'
            return _render_register(errors, values, csrf_token), 403
        if not registration_limiter.allow(_client_key()):
            errors['form'] = 'Terlalu banyak percobaan registrasi. Coba lagi nanti.'
            return _render_register(errors, values, csrf_token), 429

        password = request.form.get('password') or ''
        confirmation = request.form.get('password_confirmation') or ''
        errors = validate_registration(values['display_name'], values['email'], password)
        if password != confirmation:
            errors['password_confirmation'] = 'Konfirmasi password tidak sama.'
        if values['avatar'] and not is_valid_avatar(values['avatar']):
            errors['avatar'] = 'Pilih avatar dari daftar yang tersedia.'
        if not errors:
            try:
                user = user_store.create_user(
                    values['display_name'], values['email'], password, avatar=values['avatar'] or None
                )
                _send_verification(user)
                return redirect(url_for('auth_login', registered='1'))
            except DuplicateEmailError:
                errors['email'] = 'Email sudah terdaftar. Silakan masuk.'
            except ValueError as exc:
                errors['form'] = str(exc)

    return _render_register(errors, values, csrf_token)


def _render_register(errors, values, csrf_token):
    return render_template(
        'register.html', errors=errors, values=values, csrf_token=csrf_token,
        avatar_groups=grouped_avatars(),
    )


@app.get('/auth/verify-email/<token>')
def auth_verify_email(token):
    try:
        user = user_store.verify_email(token)
    except InvalidTokenError as exc:
        return render_template('auth_message.html', title='Verifikasi gagal', message=str(exc), ok=False), 400
    if session.get('user_id') == user.id:
        flash('Email berhasil diverifikasi.')
        return redirect(url_for('account'))
    return render_template(
        'auth_message.html', title='Email terverifikasi',
        message='Terima kasih! Email kamu sudah terverifikasi. Silakan masuk.', ok=True,
    )


@app.get('/auth/confirm-email/<token>')
def auth_confirm_email_change(token):
    try:
        user, previous_email = user_store.confirm_email_change(token)
    except (InvalidTokenError, DuplicateEmailError) as exc:
        return render_template('auth_message.html', title='Konfirmasi gagal', message=str(exc), ok=False), 400
    mailer.send_email_changed_notice(previous_email, user.display_name, user.email)
    if session.get('user_id') == user.id:
        session['user_email'] = user.email
        flash('Email berhasil diganti.')
        return redirect(url_for('account'))
    return render_template(
        'auth_message.html', title='Email diperbarui',
        message=f'Email login kamu sekarang {user.email}. Silakan masuk.', ok=True,
    )


@app.route('/auth/forgot-password', methods=['GET', 'POST'])
def auth_forgot_password():
    csrf_token = _preauth_csrf_token()
    sent = False
    error = None
    status = 200
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        if not _valid_csrf('preauth_csrf_token'):
            error, status = 'Sesi formulir kedaluwarsa. Muat ulang halaman.', 403
        elif not email_limiter.allow(f'forgot:{_client_key()}') or not email_limiter.allow(
            f'forgot-email:{email.casefold()}'
        ):
            error, status = 'Terlalu banyak permintaan. Coba lagi nanti.', 429
        else:
            result = user_store.request_password_reset(email)
            if result:
                user, token = result
                mailer.send_password_reset_email(
                    user.email, user.display_name, _external_url('auth_reset_password', token=token)
                )
            # Same response whether or not the account exists.
            sent = True
    return render_template('forgot_password.html', csrf_token=csrf_token, sent=sent, error=error), status


@app.route('/auth/reset-password/<token>', methods=['GET', 'POST'])
def auth_reset_password(token):
    csrf_token = _preauth_csrf_token()
    if not user_store.token_is_valid(token, 'reset_password'):
        return render_template(
            'auth_message.html', title='Link tidak valid',
            message='Link reset password tidak valid atau sudah kedaluwarsa. Minta link baru.',
            ok=False, action_url=url_for('auth_forgot_password'), action_label='Minta link baru',
        ), 400
    error = None
    if request.method == 'POST':
        if not _valid_csrf('preauth_csrf_token'):
            error = 'Sesi formulir kedaluwarsa. Muat ulang halaman.'
        else:
            password = request.form.get('password') or ''
            if password != (request.form.get('password_confirmation') or ''):
                error = 'Konfirmasi password tidak sama.'
            else:
                try:
                    user = user_store.reset_password(token, password)
                except (InvalidTokenError, ValueError) as exc:
                    error = str(exc)
                else:
                    mailer.send_password_changed_notice(user.email, user.display_name)
                    session.clear()
                    flash('Password berhasil direset. Silakan masuk dengan password baru.')
                    return redirect(url_for('auth_login'))
    return render_template('reset_password.html', csrf_token=csrf_token, error=error), (422 if error else 200)


@app.get('/media/avatars/<path:filename>')
def media_avatar(filename):
    path = uploaded_file_path(filename)
    if path is None:
        return jsonify(error='not found'), 404
    response = send_file(path, mimetype='image/webp', max_age=86400)
    response.headers['Content-Security-Policy'] = "default-src 'none'"
    response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
    return response


# ------------------------------------------------------------------ account
def _current_user():
    """Return the signed-in user, or None when the session is stale/revoked."""
    user = user_store.get_user(session.get('user_id', ''))
    if user is None or session.get('session_epoch', 0) != user.session_epoch:
        session.clear()
        return None
    return user


def _render_account(user, errors=None, values=None, status=200):
    flashed = get_flashed_messages(with_categories=True)
    return render_template(
        'account.html',
        user=user,
        errors=errors or {},
        values=values or {},
        avatar_groups=grouped_avatars(),
        has_uploaded_avatar=bool(upload_id(user.avatar)),
        pending_email=user_store.pending_email_change(user.id),
        bio_max_length=BIO_MAX_LENGTH,
        messages=[message for category, message in flashed if category != 'error'],
        flash_errors=[message for category, message in flashed if category == 'error'],
        csrf_token=session.get('csrf_token', ''),
    ), status


def _account_security_allowed(user):
    return account_security_limiter.allow(f"{user.id}:{_client_key()}")


def _require_user():
    user = _current_user()
    if user is None:
        return None, redirect(url_for('auth_login'))
    return user, None


@app.route('/account')
def account():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    return _render_account(user)


@app.post('/account/profile')
def account_profile():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    values = {
        'display_name': (request.form.get('display_name') or '').strip(),
        'bio': request.form.get('bio') or '',
        'avatar': (request.form.get('avatar') or '').strip(),
    }
    try:
        updated = user_store.update_profile(user.id, values['display_name'], values['bio'], values['avatar'] or None)
    except ValueError as exc:
        return _render_account(user, {'profile': str(exc)}, values, 422)
    if updated.avatar != user.avatar:
        delete_avatar_upload(user.avatar)
    session['display_name'] = updated.display_name
    flash('Profil berhasil diperbarui.')
    return redirect(url_for('account'))


@app.post('/account/avatar/upload')
def account_avatar_upload():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    if not upload_limiter.allow(user.id):
        return _render_account(user, {'upload': 'Terlalu banyak upload. Coba lagi nanti.'}, status=429)
    file = request.files.get('photo')
    data = file.read(MAX_UPLOAD_BYTES + 1) if file else b''
    try:
        avatar_value = save_avatar_upload(data)
    except AvatarUploadError as exc:
        return _render_account(user, {'upload': str(exc)}, status=422)
    user_store.set_avatar(user.id, avatar_value)
    delete_avatar_upload(user.avatar)
    flash('Foto profil berhasil diunggah.')
    return redirect(url_for('account'))


@app.post('/account/avatar/remove')
def account_avatar_remove():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    from services.avatars import default_avatar_for

    user_store.set_avatar(user.id, default_avatar_for(user.id))
    delete_avatar_upload(user.avatar)
    flash('Foto profil dihapus. Avatar default dipakai kembali.')
    return redirect(url_for('account'))


@app.post('/account/email')
def account_email():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    if not _account_security_allowed(user):
        return _render_account(user, {'email': 'Terlalu banyak percobaan. Coba lagi nanti.'}, status=429)
    new_email = (request.form.get('email') or '').strip()
    try:
        token = user_store.request_email_change(user.id, request.form.get('current_password') or '', new_email)
    except (InvalidCurrentPasswordError, DuplicateEmailError, ValueError) as exc:
        return _render_account(user, {'email': str(exc)}, {'email': new_email}, 422)
    mailer.send_email_change_confirmation(
        new_email, user.display_name, _external_url('auth_confirm_email_change', token=token)
    )
    flash(f'Link konfirmasi dikirim ke {new_email}. Email baru aktif setelah link dibuka.')
    return redirect(url_for('account'))


@app.post('/account/verify-email/resend')
def account_resend_verification():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    if user.email_verified:
        flash('Email kamu sudah terverifikasi.')
    elif not email_limiter.allow(f'verify:{user.id}'):
        flash('Terlalu banyak permintaan. Coba lagi nanti.', 'error')
    else:
        _send_verification(user)
        flash(f'Link verifikasi dikirim ke {user.email}.')
    return redirect(url_for('account'))


@app.post('/account/password')
def account_password():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    if not _account_security_allowed(user):
        return _render_account(user, {'password': 'Terlalu banyak percobaan. Coba lagi nanti.'}, status=429)
    new_password = request.form.get('new_password') or ''
    if new_password != (request.form.get('new_password_confirmation') or ''):
        return _render_account(user, {'password': 'Konfirmasi password baru tidak sama.'}, status=422)
    try:
        updated = user_store.change_password(user.id, request.form.get('current_password') or '', new_password)
    except (InvalidCurrentPasswordError, ValueError) as exc:
        return _render_account(user, {'password': str(exc)}, status=422)
    # Rotate this session and keep it valid; all other sessions are revoked by the epoch bump.
    _start_user_session(updated)
    mailer.send_password_changed_notice(updated.email, updated.display_name)
    flash('Password berhasil diganti. Sesi di perangkat lain telah dikeluarkan.')
    return redirect(url_for('account'))


@app.post('/account/export')
def account_export():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    payload = {
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'service': 'WeWatch',
        'account': user_store.export_user(user.id),
    }
    response = Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename="wewatch-account.json"'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/account/delete')
def account_delete():
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    if not _account_security_allowed(user):
        return _render_account(user, {'delete': 'Terlalu banyak percobaan. Coba lagi nanti.'}, status=429)
    if (request.form.get('confirm') or '').strip().upper() != 'HAPUS':
        return _render_account(user, {'delete': 'Ketik HAPUS untuk mengonfirmasi.'}, status=422)
    try:
        deleted = user_store.delete_user(user.id, request.form.get('current_password') or '')
    except InvalidCurrentPasswordError as exc:
        return _render_account(user, {'delete': str(exc)}, status=422)
    delete_avatar_upload(deleted.avatar)
    mailer.send_account_deleted_notice(deleted.email, deleted.display_name)
    session.clear()
    flash('Akun kamu telah dihapus permanen.')
    return redirect(url_for('auth_login'))


@app.get('/account/meeting')
def account_meeting():
    """Hand the signed-in profile to WebRTC Meet through a short-lived signed ticket."""
    user, redirect_response = _require_user()
    if redirect_response:
        return redirect_response
    avatar = user.avatar_url
    if avatar.startswith('/'):
        avatar = (PUBLIC_URL or request.url_root.rstrip('/')) + avatar
    try:
        ticket = issue_room_token(
            WEBRTC_ROOM_NAME, f'user:{user.id}', 'client', ttl=300,
            profile={'name': user.display_name, 'avatar': avatar},
        )
    except (RuntimeError, ValueError) as exc:
        logging.error('Could not issue meeting ticket: %s', exc)
        flash('Meeting belum dikonfigurasi (WEBRTC_SECRET_KEY). Hubungi administrator.', 'error')
        return redirect(url_for('account'))
    separator = '&' if '?' in WEBRTC_CLIENT_URL else '?'
    return redirect(f'{WEBRTC_CLIENT_URL}{separator}{urlencode({"join_token": ticket})}')


@app.post('/auth/logout')
def auth_logout():
    session.clear()
    return redirect(url_for('auth_login'))

@app.route('/')
def index():
    join_ticket = ''
    try:
        join_ticket = issue_room_token('gmeet_room', 'admin-dashboard', 'admin', ttl=300)
    except (RuntimeError, ValueError) as exc:
        logging.error('Could not issue short-lived WebRTC admin ticket: %s', exc)
    return render_template(
        'index.html',
        webrtc_admin_ticket=join_ticket,
        csrf_token=session.get('csrf_token', ''),
    )

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "short_name": "WeWatch",
        "name": "WeWatch Monitoring",
        "start_url": "/",
        "background_color": "#202124",
        "theme_color": "#202124",
        "display": "standalone",
        "orientation": "any"
    })

@app.route('/gallery')
def gallery():
    images = glob.glob(os.path.join(GALLERY_FOLDER, '*.jpg'))
    images.sort(key=os.path.getmtime, reverse=True)
    try:
        limit = min(max(int(request.args.get('limit', 100)), 1), 500)
    except (TypeError, ValueError):
        limit = 100
    images = images[:limit]
    image_urls = [os.path.basename(img) for img in images]
    return render_template('gallery.html', images=image_urls)

@app.route('/toggle', methods=['POST'])
def toggle():
    data = request.get_json(silent=True) or {}
    feature = data.get('feature')
    state = data.get('state')
    if feature in FEATURES:
        FEATURES[feature] = bool(state)
        logging.info(f"Feature {feature} set to {state}")
        return jsonify(success=True, feature=feature, state=FEATURES[feature])
    return jsonify(success=False, message="Feature tidak valid."), 400

@app.route('/snap_face', methods=['POST'])
def snap_face():
    if not face_limiter.allow(request.remote_addr or 'unknown'):
        return jsonify(success=False, message='Terlalu banyak percobaan registrasi wajah.'), 429
    data = request.get_json(silent=True) or {}
    name = safe_face_name(data.get('name', 'user_default'))
    success, message = camera.register_face(name)
    return jsonify(success=success, message=message), (200 if success else 422)

@app.route('/take_snapshot', methods=['POST'])
def take_snapshot():
    if not snapshot_limiter.allow(request.remote_addr or 'unknown'):
        return jsonify(success=False, message='Terlalu banyak permintaan snapshot.'), 429
    if camera.frame_rgb is not None:
        try:
            import cv2
            filename = f"snapshot_{uuid.uuid4().hex}.jpg"
            filepath = os.path.join(GALLERY_FOLDER, filename)
            bgr_frame = cv2.cvtColor(camera.frame_rgb, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filepath, bgr_frame)
            return jsonify(success=True, filename=filename, url=f"/static/gallery/{filename}", message="Foto berhasil disimpan ke galeri!")
        except Exception as e:
            return jsonify(success=False, message=str(e))
    return jsonify(success=False, message="Kamera belum siap.")

@app.route('/status_data')
def status_data():
    return jsonify({'status': STATUS, 'features': FEATURES})

@app.route('/mood_data')
def mood_data():
    try:
        conn = sqlite3.connect(str(BASE_DIR / 'mood.db'), timeout=10)
        c = conn.cursor()
        c.execute("SELECT emosi, COUNT(*) FROM mood GROUP BY emosi")
        rows = c.fetchall()
        conn.close()
        
        data = {'Senyum': 0, 'Netral': 0, 'Terkejut': 0, 'MataTertutup': 0}
        for row in rows:
            if row[0] == "Senyum": data['Senyum'] = row[1]
            elif row[0] == "Netral": data['Netral'] = row[1]
            elif row[0] == "Terkejut": data['Terkejut'] = row[1]
            elif row[0] == "Mata Tertutup": data['MataTertutup'] = row[1]
        return jsonify(data)
    except Exception as e:
        logging.error(f"Failed to fetch mood data: {e}")
        return jsonify({'Senyum': 0, 'Netral': 0, 'Terkejut': 0, 'MataTertutup': 0})

def gen_frames():
    while True:
        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(1 / 30)  # Match the camera target and avoid duplicate frames
        else:
            time.sleep(0.005)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_web_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    logging.info("Membuka Server di http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    run_web_server()
