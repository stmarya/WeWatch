import os
import glob
import sqlite3
import time
import logging
import uuid
import hmac
import secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, render_template, Response, request, jsonify, redirect, session, url_for
from dotenv import load_dotenv

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Starting The Ultimate Watcher Server...")

# Load Env
load_dotenv()

from utils.deployment_security import (
    is_loopback_host,
    parse_bool,
    validate_dashboard_config,
)
from utils.privacy import (
    RETENTION_ENV_VARS,
    purge_old_files,
    retention_days,
    start_retention_worker,
    validate_production_privacy,
)

WEBWATCH_ENV = os.getenv('WEBWATCH_ENV', 'development').strip().lower()
WEBWATCH_HOST = os.getenv('WEBWATCH_HOST', '127.0.0.1').strip()
WEBWATCH_SESSION_SECRET = os.getenv('WEBWATCH_SESSION_SECRET', '').strip()
WEBWATCH_COOKIE_SECURE = parse_bool(
    os.getenv('WEBWATCH_COOKIE_SECURE'),
    default=WEBWATCH_ENV == 'production',
)
PRIVACY_ACKNOWLEDGED = parse_bool(
    os.getenv('WEWATCH_PRIVACY_ACKNOWLEDGED'),
    default=False,
)
RETENTION_DAYS = {name: retention_days(name) for name in RETENTION_ENV_VARS}
validate_dashboard_config(
    environment=WEBWATCH_ENV,
    host=WEBWATCH_HOST,
    cookie_secure=WEBWATCH_COOKIE_SECURE,
    session_secret=WEBWATCH_SESSION_SECRET,
    privacy_acknowledged=PRIVACY_ACKNOWLEDGED,
)
validate_production_privacy(
    environment=WEBWATCH_ENV,
    privacy_acknowledged=PRIVACY_ACKNOWLEDGED,
    retention=RETENTION_DAYS,
)
WEBRTC_SECRET = os.getenv('WEBRTC_SECRET_KEY', '').strip()
WEBWATCH_ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()
if WEBWATCH_SESSION_SECRET in {WEBRTC_SECRET, WEBWATCH_ADMIN_TOKEN}:
    raise RuntimeError('Dashboard session secret must be unique to this application')

from camera import AICamera, FEATURES, STATUS
from services.jarvis import start_jarvis
from services.database import init_db, init_attendance_db, purge_expired_records
from services.room_auth import issue_room_token
from utils.security import SlidingWindowRateLimiter, safe_face_name

app = Flask(__name__)
app.config['SECRET_KEY'] = WEBWATCH_SESSION_SECRET
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = WEBWATCH_COOKIE_SECURE
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

BASE_DIR = Path(__file__).resolve().parent
GALLERY_FOLDER = str(BASE_DIR / 'static' / 'gallery')
ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()
os.makedirs(GALLERY_FOLDER, exist_ok=True)

init_db()
init_attendance_db()


def cleanup_retained_data():
    gallery_removed = purge_old_files(
        GALLERY_FOLDER,
        {'.jpg', '.jpeg', '.png'},
        RETENTION_DAYS['WEBWATCH_RETENTION_GALLERY_DAYS'],
    )
    mood_removed, attendance_removed = purge_expired_records(
        RETENTION_DAYS['WEBWATCH_RETENTION_MOOD_DAYS'],
        RETENTION_DAYS['WEBWATCH_RETENTION_ATTENDANCE_DAYS'],
    )
    face_removed = camera.purge_expired_faces()
    if gallery_removed or mood_removed or attendance_removed or face_removed:
        logging.info(
            'Privacy retention removed gallery=%s mood=%s attendance=%s face=%s',
            gallery_removed,
            mood_removed,
            attendance_removed,
            face_removed,
        )


# Initialize Camera with AI processing in background
camera = AICamera(FEATURES, STATUS)
purge_old_files(
    GALLERY_FOLDER,
    {'.jpg', '.jpeg', '.png'},
    RETENTION_DAYS['WEBWATCH_RETENTION_GALLERY_DAYS'],
)
purge_expired_records(
    RETENTION_DAYS['WEBWATCH_RETENTION_MOOD_DAYS'],
    RETENTION_DAYS['WEBWATCH_RETENTION_ATTENDANCE_DAYS'],
)
start_retention_worker(cleanup_retained_data)
login_limiter = SlidingWindowRateLimiter(max_events=8, window_seconds=60)
face_limiter = SlidingWindowRateLimiter(max_events=6, window_seconds=60)
snapshot_limiter = SlidingWindowRateLimiter(max_events=20, window_seconds=60)

# Mulai pendengar Jarvis di background
start_jarvis(camera)

@app.before_request
def require_admin_session():
    allowed = {'auth_login', 'manifest'}
    public_static = request.path.startswith('/static/') and not request.path.startswith('/static/gallery/')
    if request.endpoint in allowed or public_static:
        return None
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        expected = session.get('csrf_token', '')
        supplied = request.headers.get('X-CSRF-Token', '')
        if not expected or not hmac.compare_digest(supplied, expected):
            return jsonify(error='invalid csrf token'), 403
    if not session.get('admin_authenticated'):
        if request.path == '/':
            return redirect(url_for('auth_login'))
        return jsonify(error='authentication required'), 401
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
    if request.is_secure or WEBWATCH_ENV == 'production':
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )
    return response

@app.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    error = None
    if request.method == 'POST':
        if not login_limiter.allow(request.remote_addr or 'unknown'):
            return render_template(
                'login.html',
                error='Terlalu banyak percobaan login. Coba lagi nanti.',
            ), 429
        supplied = (request.form.get('token') or '').strip()
        if ADMIN_TOKEN and hmac.compare_digest(supplied, ADMIN_TOKEN):
            session.clear()
            session['admin_authenticated'] = True
            session['csrf_token'] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for('index'))
        error = 'Token admin tidak valid atau belum dikonfigurasi.'
    return render_template('login.html', error=error)

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
        "short_name": "Google Meet",
        "name": "Google Meet Admin",
        "icons": [
            {
                "src": "https://fonts.gstatic.com/s/i/productlogos/meet_2020q4/v6/web-512dp/logo_meet_2020q4_color_2x_web_512dp.png",
                "type": "image/png",
                "sizes": "512x512"
            }
        ],
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
    if WEBWATCH_ENV == 'production':
        raise RuntimeError(
            'Do not run the Flask development server in production; use a '
            'production WSGI server behind TLS'
        )
    if not is_loopback_host(WEBWATCH_HOST):
        raise RuntimeError('The built-in development server may bind only to loopback')
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    logging.info("Membuka Server di http://%s:5000", WEBWATCH_HOST)
    app.run(host=WEBWATCH_HOST, port=5000, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    run_web_server()
