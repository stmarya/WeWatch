"""LOOPBACK-ONLY TEST FIXTURE. Never expose this fake-camera service publicly."""
import os
import sys
import threading
from pathlib import Path
os.environ['WEBRTC_SECRET_KEY'] = 's'*64
os.environ['WEBRTC_ADMIN_TOKEN'] = 'admin-test'
os.environ['WEBRTC_REQUIRE_JOIN_TOKEN'] = 'true'
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.getenv('WEWATCH_QA_DIR', '/tmp/wewatch-qa'))
OUTPUT.mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.chdir(ROOT)
from test_dashboard_api import load_dashboard
from WebRTC_Meet import app as signaling
from services.room_auth import issue_room_token
(OUTPUT / 'join-token.txt').write_text(issue_room_token(signaling.ROOM_NAME, 'browser-qa'))
dashboard = load_dashboard()
threading.Thread(target=lambda: dashboard.app.run(host='127.0.0.1', port=5000, threaded=True, use_reloader=False), daemon=True).start()
signaling.socketio.run(signaling.app, host='127.0.0.1', port=5001, allow_unsafe_werkzeug=True, use_reloader=False)
