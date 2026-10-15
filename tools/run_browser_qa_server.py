"""LOOPBACK-ONLY TEST FIXTURE. Never expose this fake-camera service publicly."""
import os
import sys
import threading
from pathlib import Path
os.environ['WEBRTC_SECRET_KEY'] = 's'*64
os.environ['WEBRTC_ADMIN_TOKEN'] = 'admin-test'
os.environ['WEBRTC_REQUIRE_JOIN_TOKEN'] = 'true'
ROOT = Path(__file__).resolve().parents[1]
if not os.getenv('WEWATCH_QA_DIR'):
    raise SystemExit('Set WEWATCH_QA_DIR to a private directory created by mktemp -d')
OUTPUT = Path(os.environ['WEWATCH_QA_DIR'])
if not OUTPUT.is_dir() or OUTPUT.is_symlink():
    raise SystemExit('WEWATCH_QA_DIR must be an existing private directory')
if OUTPUT.stat().st_uid != os.getuid() or OUTPUT.stat().st_mode & 0o077:
    raise SystemExit('WEWATCH_QA_DIR must be owned by this user with mode 0700')
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.chdir(ROOT)
from test_dashboard_api import load_dashboard
from WebRTC_Meet import app as signaling
from services.room_auth import issue_room_token
(OUTPUT / 'join-token.txt').write_text(issue_room_token(signaling.ROOM_NAME, 'browser-qa'))
dashboard = load_dashboard()
threading.Thread(target=lambda: dashboard.app.run(host='127.0.0.1', port=5000, threaded=True, use_reloader=False), daemon=True).start()
signaling.socketio.run(signaling.app, host='127.0.0.1', port=5001, allow_unsafe_werkzeug=True, use_reloader=False)
