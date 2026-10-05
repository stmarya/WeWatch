import os
import glob
import sqlite3
import time
import logging
import uuid
import hmac
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, request, jsonify, redirect, session, url_for, flash, get_flashed_messages
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
from services.avatars import grouped_avatars, is_valid_avatar
from services.user_store import (
    BIO_MAX_LENGTH, DuplicateEmailError, InvalidCurrentPasswordError, UserStore, validate_registration,
)
from utils.security import SlidingWindowRateLimiter, safe_face_name

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv(
    'WEBWATCH_SESSION_SECRET',
    os.getenv('WEBRTC_SECRET_KEY', os.urandom(32).hex()),
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('WEBWATCH_COOKIE_SECURE', 'false').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

BASE_DIR = Path(__file__).resolve().parent
GALLERY_FOLDER = str(BASE_DIR / 'static' / 'gallery')
ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()
USERS_DB = Path(os.getenv('WEBWATCH_USERS_DB', 'users.db'))
if not USERS_DB.is_absolute():
    USERS_DB = BASE_DIR / USERS_DB
os.makedirs(GALLERY_FOLDER, exist_ok=True)
user_store = UserStore(USERS_DB)

init_db()
init_attendance_db()

# Initialize Camera with AI processing in background
camera = AICamera(FEATURES, STATUS)
login_limiter = SlidingWindowRateLimiter(max_events=8, window_seconds=60)
registration_limiter = SlidingWindowRateLimiter(max_events=5, window_seconds=600)
# Email/password changes require the current password; throttle guessing per account.
account_security_limiter = SlidingWindowRateLimiter(max_events=10, window_seconds=600)
face_limiter = SlidingWindowRateLimiter(max_events=6, window_seconds=60)
snapshot_limiter = SlidingWindowRateLimiter(max_events=20, window_seconds=60)

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


ACCOUNT_ENDPOINTS = {'account', 'account_profile', 'account_email', 'account_password'}
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
    public_endpoints = {'auth_login', 'auth_register', 'manifest'}
    public_static = request.path.startswith('/static/') and not request.path.startswith('/static/gallery/')
    if request.endpoint in public_endpoints or public_static:
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


@app.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    error = None
    registered = request.args.get('registered') == '1'
    csrf_token = _preauth_csrf_token()
    if request.method == 'POST':
        if not _valid_csrf('preauth_csrf_token'):
            return render_template('login.html', error='Sesi formulir kedaluwarsa. Muat ulang halaman.', csrf_token=csrf_token, registered=False), 403
        if not login_limiter.allow(request.remote_addr or 'unknown'):
            return render_template(
                'login.html', error='Terlalu banyak percobaan login. Coba lagi nanti.',
                csrf_token=csrf_token, registered=False,
            ), 429

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
                _start_authenticated_session(
                    user_id=user.id,
                    user_email=user.email,
                    display_name=user.display_name,
                    role=user.role,
                    session_epoch=user.session_epoch,
                )
                return redirect(url_for('account'))
        # Do not disclose whether an email exists or which credential failed.
        error = 'Email/password atau token admin tidak valid.'

    return render_template('login.html', error=error, csrf_token=csrf_token, registered=registered)


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
        if not registration_limiter.allow(request.remote_addr or 'unknown'):
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
                user_store.create_user(
                    values['display_name'], values['email'], password, avatar=values['avatar'] or None
                )
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


def _current_user():
    """Return the signed-in user, or None when the session is stale/revoked."""
    user = user_store.get_user(session.get('user_id', ''))
    if user is None or session.get('session_epoch', 0) != user.session_epoch:
        session.clear()
        return None
    return user


def _render_account(user, errors=None, values=None, status=200):
    return render_template(
        'account.html',
        user=user,
        errors=errors or {},
        values=values or {},
        avatar_groups=grouped_avatars(),
        bio_max_length=BIO_MAX_LENGTH,
        messages=get_flashed_messages(),
        csrf_token=session.get('csrf_token', ''),
    ), status


def _account_security_allowed(user):
    return account_security_limiter.allow(f"{user.id}:{request.remote_addr or 'unknown'}")


@app.route('/account')
def account():
    user = _current_user()
    if user is None:
        return redirect(url_for('auth_login'))
    return _render_account(user)


@app.post('/account/profile')
def account_profile():
    user = _current_user()
    if user is None:
        return redirect(url_for('auth_login'))
    values = {
        'display_name': (request.form.get('display_name') or '').strip(),
        'bio': request.form.get('bio') or '',
        'avatar': (request.form.get('avatar') or '').strip(),
    }
    try:
        updated = user_store.update_profile(user.id, values['display_name'], values['bio'], values['avatar'] or None)
    except ValueError as exc:
        return _render_account(user, {'profile': str(exc)}, values, 422)
    session['display_name'] = updated.display_name
    flash('Profil berhasil diperbarui.')
    return redirect(url_for('account'))


@app.post('/account/email')
def account_email():
    user = _current_user()
    if user is None:
        return redirect(url_for('auth_login'))
    if not _account_security_allowed(user):
        return _render_account(user, {'email': 'Terlalu banyak percobaan. Coba lagi nanti.'}, status=429)
    new_email = (request.form.get('email') or '').strip()
    try:
        updated = user_store.change_email(user.id, request.form.get('current_password') or '', new_email)
    except (InvalidCurrentPasswordError, DuplicateEmailError, ValueError) as exc:
        return _render_account(user, {'email': str(exc)}, {'email': new_email}, 422)
    session['user_email'] = updated.email
    flash('Email berhasil diperbarui.')
    return redirect(url_for('account'))


@app.post('/account/password')
def account_password():
    user = _current_user()
    if user is None:
        return redirect(url_for('auth_login'))
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
    _start_authenticated_session(
        user_id=updated.id,
        user_email=updated.email,
        display_name=updated.display_name,
        role=updated.role,
        session_epoch=updated.session_epoch,
    )
    flash('Password berhasil diganti. Sesi di perangkat lain telah dikeluarkan.')
    return redirect(url_for('account'))


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
