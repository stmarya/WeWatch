import os
import logging
import sys
import json
import uuid
import hmac
import time
import math
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from functools import wraps
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
try:
    from services.room_auth import issue_room_token, verify_room_token
    from services.livekit_tokens import issue_livekit_token
except ModuleNotFoundError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from services.room_auth import issue_room_token, verify_room_token
    from services.livekit_tokens import issue_livekit_token
try:
    from shared_state import SharedParticipants
except ModuleNotFoundError:
    from WebRTC_Meet.shared_state import SharedParticipants
try:
    from room_store import RoomStore
except ModuleNotFoundError:
    from WebRTC_Meet.room_store import RoomStore
from utils.security import SlidingWindowRateLimiter

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
app.config['SECRET_KEY'] = os.getenv('WEBRTC_SECRET_KEY', os.urandom(32).hex())
_configured_origins = os.getenv(
    'WEBRTC_ALLOWED_ORIGINS',
    'http://localhost:5000,http://localhost:5001,'
    'http://127.0.0.1:5000,http://127.0.0.1:5001',
)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _configured_origins.split(',')
    if origin.strip()
]
socketio = SocketIO(
    app,
    message_queue=os.getenv('REDIS_URL') or None,
    cors_allowed_origins=ALLOWED_ORIGINS,
    ping_interval=25,
    ping_timeout=60,
    # Remote screenshots can be several megabytes after base64 encoding.
    max_http_buffer_size=10_000_000,
)

ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()
DESKTOP_AGENT_TOKEN = os.getenv('DESKTOP_AGENT_TOKEN', '').strip()
ALLOW_STATIC_AGENT_TOKEN = os.getenv('WEBRTC_ALLOW_STATIC_AGENT_TOKEN', 'false').lower() == 'true'
REQUIRE_JOIN_TOKEN = os.getenv('WEBRTC_REQUIRE_JOIN_TOKEN', 'true').lower() == 'true'
REQUIRE_SHARED_STATE = os.getenv('WEBRTC_REQUIRE_SHARED_STATE', 'false').lower() == 'true'
ROOM_NAME = os.getenv('WEBRTC_ROOM_NAME', 'gmeet_room')
LIVEKIT_URL = os.getenv('LIVEKIT_URL', 'ws://localhost:7880').strip()
ALLOW_UNSAFE_WERKZEUG = os.getenv(
    'WEBRTC_ALLOW_UNSAFE_WERKZEUG', 'true'
).lower() == 'true'
try:
    MAX_PARTICIPANTS = max(1, int(os.getenv('WEBRTC_MAX_PARTICIPANTS', '600')))
except (ValueError, RuntimeError):
    MAX_PARTICIPANTS = 600
ALLOWED_REMOTE_COMMANDS = {
    'ring_bell', 'tts_speak', 'force_fullscreen', 'toggle_cam',
    'reload_page', 'hr_warning_banner', 'hr_session_lock',
    'hr_session_unlock', 'open_url',
}
# Shared state is Redis-backed when REDIS_URL is configured and local otherwise.
participants = SharedParticipants(os.getenv('REDIS_URL'), ROOM_NAME)
room_store = RoomStore(os.getenv('REDIS_URL'), ROOM_NAME)
DEFAULT_HOST_PERMISSIONS = {'screen': True, 'chat': True, 'mic': True, 'video': True}
join_limiter = SlidingWindowRateLimiter(max_events=1000, window_seconds=60)
room_token_limiter = SlidingWindowRateLimiter(max_events=1000, window_seconds=60)
livekit_token_limiter = SlidingWindowRateLimiter(max_events=1000, window_seconds=60)
socket_event_limiters = {
    'general': SlidingWindowRateLimiter(max_events=1000, window_seconds=10),
    'chat': SlidingWindowRateLimiter(max_events=30, window_seconds=10),
    'caption': SlidingWindowRateLimiter(max_events=30, window_seconds=10),
    'whiteboard': SlidingWindowRateLimiter(max_events=120, window_seconds=10),
    # Mouse move events can be high frequency; keep this limit high enough
    # to avoid making remote pointer control visibly choppy.
    'desktop': SlidingWindowRateLimiter(max_events=600, window_seconds=10),
}


def _as_dict(data):
    return data if isinstance(data, dict) else {}


def allow_socket_event(name):
    limiter = socket_event_limiters[name]
    if limiter.allow(f'{name}:{request.sid}'):
        return True
    emit('rate_limited', {'event': name, 'retry_after': 10}, to=request.sid)
    return False


@app.get('/healthz')
def healthz():
    return jsonify(status='ok', service='webrtc-signaling')


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(self), microphone=(self), geolocation=(), payment=()',
    )
    if request.is_secure:
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )
    return response


@app.get('/readyz')
def readyz():
    if REQUIRE_JOIN_TOKEN and len(os.getenv('WEBRTC_SECRET_KEY', '')) < 32:
        return jsonify(status='not_ready', reason='WEBRTC_SECRET_KEY is missing'), 503
    if REQUIRE_SHARED_STATE and (
        not participants.shared
        or not room_store.shared
        or not participants.healthy()
        or not room_store.healthy()
    ):
        return jsonify(status='not_ready', reason='Shared Redis state is unavailable'), 503
    return jsonify(status='ready')


@app.post('/api/room-token')
def room_token():
    if not room_token_limiter.allow(request.remote_addr or 'unknown'):
        return jsonify(error='too many token requests'), 429
    if not ADMIN_TOKEN or not hmac.compare_digest(request.headers.get('X-Admin-Token', ''), ADMIN_TOKEN):
        return jsonify(error='admin authentication required'), 401
    data = _as_dict(request.get_json(silent=True))
    identity = str(data.get('identity', '')).strip()
    role = str(data.get('role', 'client')).strip()
    room = str(data.get('room', ROOM_NAME)).strip() or ROOM_NAME
    if not identity or role not in {'admin', 'client', 'agent'}:
        return jsonify(error='identity and valid role are required'), 400
    if room != ROOM_NAME:
        return jsonify(error='room does not match the configured signaling room'), 400
    try:
        ttl = int(data.get('ttl', 3600))
        join_token = issue_room_token(room, identity, role, ttl, target_identity=data.get('target_identity'))
    except (ValueError, TypeError, OverflowError, RuntimeError) as exc:
        return jsonify(error=str(exc)), 400
    try:
        livekit_token = issue_livekit_token(room, identity, ttl)
    except RuntimeError:
        livekit_token = None
    return jsonify(
        join_token=join_token,
        livekit_token=livekit_token,
        room=room,
        identity=identity,
        role=role,
    )


@app.post('/api/livekit-token')
def livekit_token():
    """Exchange a short-lived room token for a LiveKit media token.

    The room token binds the identity and room before LiveKit credentials are
    issued, so browsers never need the admin secret or LiveKit API secret.
    """
    if not livekit_token_limiter.allow(request.remote_addr or 'unknown'):
        return jsonify(error='too many token requests'), 429
    data = _as_dict(request.get_json(silent=True))
    room_token_value = str(data.get('join_token', '')).strip()
    if not room_token_value:
        return jsonify(error='join_token is required'), 401
    try:
        claims = verify_room_token(room_token_value, ROOM_NAME)
        if claims.get('role') not in {'admin', 'client'}:
            raise ValueError('unsupported media role')
        if claims['role'] == 'client' and is_meeting_locked():
            return jsonify(error='meeting locked'), 403
        ttl = int(data.get('ttl', 3600))
        remaining = int(claims['exp']) - int(time.time())
        if remaining <= 0:
            raise ValueError('room token expired')
        token = issue_livekit_token(ROOM_NAME, claims['identity'], min(ttl, remaining), min_ttl=1)
    except (ValueError, RuntimeError, KeyError) as exc:
        return jsonify(error=str(exc)), 401
    return jsonify(
        livekit_token=token,
        livekit_url=LIVEKIT_URL,
        room=ROOM_NAME,
        identity=claims['identity'],
        role=claims['role'],
    )



def require_participant(handler):
    """A socket transport connection is not an authenticated room membership."""
    @wraps(handler)
    def guarded(*args, **kwargs):
        user = participants.get(request.sid, {})
        if user.get('role') not in {'admin', 'client', 'agent'}:
            emit('action_rejected', {'reason': 'Join authentication required.'}, to=request.sid)
            return
        if user.get('role') == 'agent' and handler.__name__ != 'handle_agent_action_result':
            return
        if not socket_event_limiters['general'].allow(request.sid):
            emit('rate_limited', {'event': 'room', 'retry_after': 10}, to=request.sid)
            return
        return handler(*args, **kwargs)
    return guarded


def remote_consent(target):
    user = participants.get(target, {})
    return user.get('role') == 'client' and user.get('remote_consent_until', 0) > time.time()


def require_remote_consent(target):
    if not remote_consent(target):
        emit_remote_error('Participant remote-assistance consent is required (expires after 10 minutes).')
        return False
    return True


def public_poll(poll):
    return {key: value for key, value in poll.items() if key != 'voters'}


def is_admin(sid):
    return participants.get(sid, {}).get('role') == 'admin'


def require_admin():
    if not is_admin(request.sid):
        emit('action_rejected', {'reason': 'Host permission required.'}, to=request.sid)
        return False
    return True


def get_host_permissions():
    permissions = room_store.get('host_permissions')
    if not isinstance(permissions, dict):
        permissions = dict(DEFAULT_HOST_PERMISSIONS)
        room_store.set('host_permissions', permissions)
    return permissions


def is_meeting_locked():
    return bool(room_store.get('meeting_locked', False))


def get_active_poll():
    poll = room_store.get('active_poll')
    return poll if isinstance(poll, dict) else None


def get_whiteboard_history():
    history = room_store.get('whiteboard_history', [])
    return history if isinstance(history, list) else []


def emit_remote_error(message):
    emit('desktop_action_result', {'status': 'error', 'msg': message}, to=request.sid)


def valid_remote_target(target):
    if not isinstance(target, str) or target == request.sid:
        return False
    target_user = participants.get(target)
    return isinstance(target_user, dict) and target_user.get('role') == 'client'


def require_remote_client_target(data):
    """Require every OS-level remote action to target a connected client."""
    target = data.get('target') if isinstance(data, dict) else None
    if not valid_remote_target(target):
        emit_remote_error('A connected client target is required for remote desktop control.')
        return None
    return target


def public_participants():
    return [user for user in participants.values() if user.get('role') != 'agent']


def resolve_agent_sid(target):
    if isinstance(target, str) and target in participants:
        if participants.get(target, {}).get('role') == 'agent':
            return target
        target_identity = participants.get(target, {}).get('identity')
    else:
        target_identity = target
    if not isinstance(target_identity, str) or not target_identity:
        return None
    for sid, user in participants.items():
        if user.get('role') == 'agent' and user.get('target_identity') == target_identity:
            return sid
    return None


def dispatch_to_agent(target, command, payload=None):
    agent_sid = resolve_agent_sid(target)
    if not agent_sid:
        emit_remote_error('No paired desktop agent is connected for this client.')
        return True
    request_id = uuid.uuid4().hex
    room_store.set('desktop_request:' + request_id, {
        'agent_sid': agent_sid, 'reply_to': request.sid, 'target': target,
        'expires_at': time.time() + 30,
    }, ttl=30)
    emit(
        'desktop_command',
        {
            'request_id': request_id,
            'issued_at': time.time(),
            'expires_at': time.time() + 30,
            'command': command,
            'payload': payload or {},
            'reply_to': request.sid,
        },
        to=agent_sid,
    )
    return True

@app.route('/')
@app.route('/client')
def client_page():
    return render_template('client.html')


@app.route('/livekit')
def livekit_page():
    return render_template(
        'livekit.html',
        livekit_configured=bool(
            os.getenv('LIVEKIT_API_KEY', '').strip()
            and os.getenv('LIVEKIT_API_SECRET', '').strip()
            and LIVEKIT_URL
        ),
    )


@app.route('/admin')
def admin_page():
    # Use the authenticated root dashboard as the canonical admin surface.
    # Keeping a token in a query string on this legacy page is unsafe.
    return redirect(os.getenv('ADMIN_DASHBOARD_URL', 'http://localhost:5000'))

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "short_name": "WeWatch",
        "name": "WeWatch Client",
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

@socketio.on('join')
def handle_join(data):
    data = data if isinstance(data, dict) else {}
    if not join_limiter.allow(request.remote_addr or 'unknown'):
        emit('join_rejected', {'reason': 'Too many join attempts. Try again later.'})
        return
    if request.sid in participants:
        emit('join_rejected', {'reason': 'Already joined; reconnect to change identity.'})
        return
    if REQUIRE_SHARED_STATE and (not participants.healthy() or not room_store.healthy()):
        emit('join_rejected', {'reason': 'Required shared state is unavailable.'})
        return
    requested_role = data.get('role', 'client')
    if requested_role not in ('admin', 'agent', 'client'):
        emit('join_rejected', {'reason': 'Invalid participant role.'})
        return
    identity = str(data.get('identity', request.sid[:12])).strip()[:128]
    if requested_role == 'agent':
        static_agent_ok = ALLOW_STATIC_AGENT_TOKEN and bool(DESKTOP_AGENT_TOKEN) and hmac.compare_digest(
            str(data.get('agent_token', '')), DESKTOP_AGENT_TOKEN
        )
        ticket_ok = False
        if not static_agent_ok:
            try:
                claims = verify_room_token(data.get('join_token', ''), ROOM_NAME, identity)
                ticket_ok = (claims['role'] == 'agent' and isinstance(claims.get('target_identity'), str)
                             and claims['target_identity'] == data.get('target_identity'))
            except (ValueError, RuntimeError):
                ticket_ok = False
        if not (static_agent_ok or ticket_ok):
            emit('join_rejected', {'reason': 'Desktop agent authentication required.'})
            return
    elif requested_role == 'admin':
        static_token_ok = bool(ADMIN_TOKEN) and hmac.compare_digest(
            str(data.get('token', '')), ADMIN_TOKEN
        )
        ticket_ok = False
        if not static_token_ok:
            try:
                claims = verify_room_token(data.get('join_token', ''), ROOM_NAME, identity)
                ticket_ok = claims['role'] == 'admin'
            except (ValueError, RuntimeError):
                ticket_ok = False
        if not (static_token_ok or ticket_ok):
            emit('join_rejected', {'reason': 'Admin token required.'})
            return
    role = requested_role if requested_role in {'admin', 'agent'} else 'client'
    if role == 'client' and (REQUIRE_JOIN_TOKEN or data.get('join_token')):
        try:
            claims = verify_room_token(data.get('join_token', ''), ROOM_NAME, data.get('identity') or None)
            identity = claims['identity']
            if claims['role'] != 'client':
                raise ValueError('role mismatch')
        except (ValueError, RuntimeError):
            emit('join_rejected', {'reason': 'Valid room token required.'})
            return
    
    if is_meeting_locked() and role == 'client':
        emit('join_rejected', {'reason': 'This meeting has been locked by the host.'})
        return
    if role == 'client':
        connected_clients = sum(
            1 for participant in participants.values()
            if participant.get('role') == 'client'
        )
        if connected_clients >= MAX_PARTICIPANTS:
            emit(
                'join_rejected',
                {'reason': f'Meeting capacity reached ({MAX_PARTICIPANTS} participants).'},
            )
            return

    if not identity or any(user.get('identity') == identity for user in participants.values()):
        emit('join_rejected', {'reason': 'Identity is empty or already connected.'})
        return
    name = str(data.get('name') or ('Admin (Host)' if role == 'admin' else 'Participant'))[:128]
    room = ROOM_NAME
    join_room(room)
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    participants[request.sid] = {
        'id': request.sid,
        'name': name,
        'role': role,
        'identity': identity,
        'target_identity': str(data.get('target_identity', '')).strip()[:128] if role == 'agent' else '',
        'mic': data.get('mic', True),
        'cam': data.get('cam', True),
        'screen': False,
        'hand': False,
        'joined_at': now_str
    }
    emit('join_accepted', {'identity': identity, 'role': role}, to=request.sid)
    print(f"[{role.upper()}] joined: {name} ({request.sid}) at {now_str}")
    
    # Send current participant list, lock state, and host permissions to newly joined user
    emit('participants_update', public_participants())
    emit('meeting_lock_changed', {'locked': is_meeting_locked()})
    emit('host_permissions_update', get_host_permissions())
    active_poll = get_active_poll()
    if active_poll:
        emit('poll_created', public_poll(active_poll))
    
    # Broadcast to other participants
    if role != 'agent':
        emit('user_joined', participants[request.sid], to=room, include_self=False)
    
    # Specifically inform admin of client joined for WebRTC peering
    if role == 'client':
        emit('client_joined', {'id': request.sid, 'name': name}, to=room)


@socketio.on('remote_assistance_consent')
@require_participant
def handle_remote_assistance_consent(data):
    user = participants.get(request.sid, {})
    if user.get('role') != 'client':
        return
    granted = _as_dict(data).get('granted') is True
    user['remote_consent_until'] = time.time() + 600 if granted else 0
    participants[request.sid] = user
    emit('remote_consent_updated', {'granted': granted}, to=request.sid)


@socketio.on('presence_ping')
def handle_presence_ping():
    if request.sid in participants:
        participants.refresh(request.sid)


@socketio.on('agent_action_result')
@require_participant
def handle_agent_action_result(data):
    agent = participants.get(request.sid, {})
    if agent.get('role') != 'agent' or not isinstance(data, dict):
        return
    reply_to = data.get('reply_to')
    request_id = data.get('request_id')
    if not isinstance(request_id, str) or len(request_id) > 64:
        return
    if not isinstance(reply_to, str) or participants.get(reply_to, {}).get('role') != 'admin':
        return
    pending = room_store.get('desktop_request:' + request_id)
    if (not isinstance(pending, dict) or pending.get('agent_sid') != request.sid
            or pending.get('reply_to') != reply_to or pending.get('expires_at', 0) <= time.time()):
        return
    room_store.delete('desktop_request:' + request_id)
    if not remote_consent(pending.get('target')):
        return
    result = {
        'status': 'success' if data.get('ok') else 'error',
        'msg': str(data.get('message', 'Desktop agent completed the request.'))[:1000],
    }
    emit('desktop_action_result', result, to=reply_to)
    screenshot = data.get('screenshot_b64')
    if isinstance(screenshot, str) and len(screenshot) <= 8_000_000:
        emit('desktop_screenshot_data', {'b64': screenshot}, to=reply_to)

@socketio.on('webrtc_offer')
@require_participant
def handle_offer(data):
    data = _as_dict(data)
    target = data.get('target')
    if (isinstance(target, str) and target in participants
            and {participants[request.sid]['role'], participants[target].get('role')} == {'admin', 'client'}):
        data['sender'] = request.sid
        emit('webrtc_offer', data, to=target)

@socketio.on('webrtc_answer')
@require_participant
def handle_answer(data):
    data = _as_dict(data)
    target = data.get('target')
    if (isinstance(target, str) and target in participants
            and {participants[request.sid]['role'], participants[target].get('role')} == {'admin', 'client'}):
        data['sender'] = request.sid
        emit('webrtc_answer', data, to=target)

@socketio.on('webrtc_ice_candidate')
@require_participant
def handle_ice(data):
    data = _as_dict(data)
    target = data.get('target')
    if (isinstance(target, str) and target in participants
            and {participants[request.sid]['role'], participants[target].get('role')} == {'admin', 'client'}):
        data['sender'] = request.sid
        emit('webrtc_ice_candidate', data, to=target)

@socketio.on('chat_message')
@require_participant
def handle_chat_message(data):
    data = _as_dict(data)
    if not allow_socket_event('chat'):
        return
    user = participants.get(request.sid, {})
    if user.get('role') == 'client' and not get_host_permissions().get('chat', True):
        emit('chat_rejected', {'reason': 'Chat has been disabled by the meeting host.'})
        return

    message_payload = {
        'senderId': request.sid,
        'senderName': user.get('name', data.get('name', 'User')),
        'senderRole': user.get('role', 'client'),
        'text': str(data.get('text', ''))[:2000],
        'time': datetime.now().strftime('%I:%M %p')
    }
    emit('chat_message', message_payload, to=ROOM_NAME)

@socketio.on('live_caption')
@require_participant
def handle_live_caption(data):
    # Broadcast live speech transcript to everyone in call
    if isinstance(data, dict) and allow_socket_event('caption'):
        user = participants.get(request.sid, {})
        payload = {
            'name': str(user.get('name') or data.get('name') or 'Participant')[:128],
            'text': str(data.get('text', ''))[:2000],
        }
        emit('caption_broadcast', payload, to=ROOM_NAME)

@socketio.on('update_host_permission')
@require_participant
def handle_update_host_permission(data):
    data = _as_dict(data)
    if not require_admin():
        return
    perm = data.get('perm')
    allowed = bool(data.get('allowed', True))
    permissions = get_host_permissions()
    if perm in permissions:
        permissions[perm] = allowed
        room_store.set('host_permissions', permissions)
        print(f"[SECURITY] Host permission '{perm}' set to: {allowed}")
        emit('host_permissions_update', permissions, to=ROOM_NAME)

@socketio.on('toggle_media')
@require_participant
def handle_toggle_media(data):
    data = _as_dict(data)
    if request.sid in participants:
        media_type = data.get('type') # 'mic' or 'cam'
        if media_type not in ('mic', 'cam', 'screen'):
            return
        enabled = data.get('enabled') is True
        permission_key = {'cam': 'video', 'mic': 'mic', 'screen': 'screen'}[media_type]
        if enabled and not is_admin(request.sid) and not get_host_permissions().get(permission_key, True):
            emit('action_rejected', {'reason': 'Media disabled by host.'}, to=request.sid)
            return
        user = participants[request.sid]
        user[media_type] = enabled
        participants[request.sid] = user
        emit('user_media_toggled', {
            'id': request.sid,
            'type': media_type,
            'enabled': enabled
        }, to=ROOM_NAME)

@socketio.on('raise_hand')
@require_participant
def handle_raise_hand(data):
    data = _as_dict(data)
    if request.sid in participants:
        raised = data.get('raised', False)
        user = participants[request.sid]
        user['hand'] = bool(raised)
        participants[request.sid] = user
        emit('user_hand_raised', {
            'id': request.sid,
            'name': participants[request.sid]['name'],
            'raised': raised
        }, to=ROOM_NAME)

@socketio.on('reaction_emoji')
@require_participant
def handle_reaction(data):
    data = _as_dict(data)
    allowed = {'👍', '👏', '❤️', '😂', '😮', '😢', '🎉'}
    emoji = data.get('emoji', '👍')
    emit('reaction_emoji', {
        'senderId': request.sid,
        'emoji': emoji if emoji in allowed else '👍'
    }, to=ROOM_NAME)

@socketio.on('recording_state')
@require_participant
def handle_recording_state(data):
    data = _as_dict(data)
    if not require_admin():
        return
    emit('recording_state', {
        'isRecording': bool(data.get('isRecording', False))
    }, to=ROOM_NAME)

# Host-specific moderation events
@socketio.on('admin_mute_client')
@require_participant
def handle_mute_client(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target_id = data.get('target')
    if isinstance(target_id, str) and target_id in participants:
        user = participants[target_id]
        user['mic'] = False
        participants[target_id] = user
        emit('force_mute', {}, to=target_id)
        emit('user_media_toggled', {'id': target_id, 'type': 'mic', 'enabled': False}, to=ROOM_NAME)

@socketio.on('admin_mute_all')
@require_participant
def handle_mute_all():
    if not require_admin():
        return
    for sid, u in participants.items():
        if u['role'] == 'client':
            u['mic'] = False
            participants[sid] = u
            emit('force_mute', {}, to=sid)
            emit('user_media_toggled', {'id': sid, 'type': 'mic', 'enabled': False}, to=ROOM_NAME)

@socketio.on('admin_kick_client')
@require_participant
def handle_kick_client(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target_id = data.get('target')
    if isinstance(target_id, str) and target_id in participants:
        emit('force_disconnect', {'reason': 'You were removed by the meeting host.'}, to=target_id)
        disconnect(target_id)

@socketio.on('admin_end_all')
@require_participant
def handle_end_all():
    if not require_admin():
        return
    room_store.set('meeting_locked', True)
    emit('meeting_ended_by_host', {'reason': 'The meeting was ended for everyone by the host.'}, to=ROOM_NAME)
    for sid, user in list(participants.items()):
        if user.get('role') != 'admin':
            disconnect(sid)

# Meeting Lock Security
@socketio.on('toggle_meeting_lock')
@require_participant
def handle_toggle_meeting_lock(data):
    data = _as_dict(data)
    if not require_admin():
        return
    locked = bool(data.get('locked', False))
    room_store.set('meeting_locked', locked)
    print(f"[SECURITY] Meeting locked state: {locked}")
    emit('meeting_lock_changed', {'locked': locked}, to=ROOM_NAME)

# Collaborative Whiteboard Events
@socketio.on('whiteboard_draw')
@require_participant
def handle_whiteboard_draw(data):
    if not allow_socket_event('whiteboard'):
        return
    if not isinstance(data, dict) or len(json.dumps(data)) > 10000:
        return
    if any(not isinstance(data.get(k), (int, float)) or isinstance(data.get(k), bool)
           or not math.isfinite(data[k]) or not 0 <= data[k] <= 1
           for k in ('x0', 'y0', 'x1', 'y1')):
        return
    size = data.get('size', 4)
    color = data.get('color', '#ffffff')
    if (not isinstance(size, (int, float)) or not math.isfinite(size) or not 1 <= size <= 40
            or not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', color)):
        return
    data = {key: data[key] for key in ('x0', 'y0', 'x1', 'y1')} | {'size': size, 'color': color}
    def append_stroke(history):
        history = history if isinstance(history, list) else []
        return (history + [data])[-2000:]

    room_store.update('whiteboard_history', append_stroke, default=[], ttl=86400)
    emit('whiteboard_draw', data, to=ROOM_NAME, include_self=False)

@socketio.on('whiteboard_clear')
@require_participant
def handle_whiteboard_clear():
    if not require_admin():
        return
    room_store.set('whiteboard_history', [])
    emit('whiteboard_clear', {}, to=ROOM_NAME)

@socketio.on('whiteboard_request_sync')
@require_participant
def handle_whiteboard_sync():
    emit('whiteboard_full_sync', {'strokes': get_whiteboard_history()})

# In-Meeting Live Polls Events
@socketio.on('create_poll')
@require_participant
def handle_create_poll(data):
    data = _as_dict(data)
    if not require_admin():
        return
    question = str(data.get('question', '')).strip()[:500]
    raw_options = data.get('options', [])
    options = [
        str(option).strip()[:120]
        for option in raw_options
        if str(option).strip()
    ] if isinstance(raw_options, list) else []
    options = list(dict.fromkeys(options))[:8]
    if not question or len(options) < 2:
        return
    
    active_poll = {
        'id': f"poll_{uuid.uuid4().hex}",
        'question': question,
        'options': [{'text': opt, 'votes': 0} for opt in options],
        'voters': {}, # sid -> optionIndex
        'active': True,
        'creator': participants.get(request.sid, {}).get('name', 'Host')
    }
    room_store.set('active_poll', active_poll)
    print(f"[POLL] Created: {question} with {len(options)} options")
    emit('poll_created', public_poll(active_poll), to=ROOM_NAME)

@socketio.on('submit_vote')
@require_participant
def handle_submit_vote(data):
    data = _as_dict(data)
    active_poll = get_active_poll()
    if not active_poll or not active_poll.get('active'):
        return
    
    poll_id = data.get('pollId')
    option_idx = data.get('optionIndex')
    if active_poll['id'] != poll_id:
        return
    if not isinstance(option_idx, int) or not 0 <= option_idx < len(active_poll['options']):
        emit('poll_error', {'reason': 'Invalid poll option.'}, to=request.sid)
        return
    
    voter_identity = participants[request.sid]['identity']
    def apply_vote(current):
        if (
            not isinstance(current, dict)
            or current.get('id') != poll_id
            or not current.get('active')
            or not isinstance(current.get('options'), list)
            or not 0 <= option_idx < len(current['options'])
        ):
            return current
        voters = current.setdefault('voters', {})
        previous = voters.get(voter_identity)
        if previous == option_idx:
            return current
        if isinstance(previous, int) and 0 <= previous < len(current['options']):
            current['options'][previous]['votes'] = max(
                0, int(current['options'][previous].get('votes', 0)) - 1
            )
        voters[voter_identity] = option_idx
        current['options'][option_idx]['votes'] = int(
            current['options'][option_idx].get('votes', 0)
        ) + 1
        return current

    active_poll = room_store.update('active_poll', apply_vote, default=None)
    if not isinstance(active_poll, dict) or active_poll.get('id') != poll_id:
        return
    
    emit('poll_updated', {
        'id': active_poll['id'],
        'options': active_poll['options'],
        'totalVotes': len(active_poll['voters'])
    }, to=ROOM_NAME)

@socketio.on('end_poll')
@require_participant
def handle_end_poll(data):
    data = _as_dict(data)
    if not require_admin():
        return
    active_poll = get_active_poll()
    if active_poll:
        active_poll['active'] = False
        room_store.set('active_poll', active_poll)
        emit('poll_ended', {'id': active_poll['id']}, to=ROOM_NAME)

# =========================================================================
# HOST REMOTE CONTROL & PROCTORING EVENTS
# =========================================================================

@socketio.on('client_proctor_alert')
@require_participant
def handle_proctor_alert(data):
    user = participants.get(request.sid, {})
    event = str(_as_dict(data).get('event', 'unknown'))[:200]
    payload = {
        'id': request.sid,
        'name': user.get('name', 'Participant'),
        'event': event,
        'time': datetime.now().strftime('%H:%M:%S')
    }
    # An empty target list is a broadcast in some Socket.IO versions.
    for sid, participant in participants.items():
        if participant.get('role') == 'admin':
            emit('admin_proctor_alert', payload, to=sid)


@socketio.on('client_proctor_event')
@require_participant
def handle_proctor_event(data):
    handle_proctor_alert(data)


# =========================================================================
# OS-LEVEL REMOTE DESKTOP CONTROL (HR & MANAGER TAKEOVER)
# =========================================================================

@socketio.on('desktop_mouse_move')
@require_participant
def handle_desktop_mouse_move(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None or not require_remote_consent(target):
        return
    dispatch_to_agent(target, 'mouse_move', {
        'xRatio': data.get('xRatio', 0), 'yRatio': data.get('yRatio', 0)
    })

@socketio.on('desktop_mouse_click')
@require_participant
def handle_desktop_mouse_click(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None or not require_remote_consent(target):
        return
    dispatch_to_agent(target, 'mouse_click', {
        'xRatio': data.get('xRatio', 0), 'yRatio': data.get('yRatio', 0),
        'button': data.get('button', 'left')
    })

@socketio.on('desktop_mouse_scroll')
@require_participant
def handle_desktop_mouse_scroll(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None or not require_remote_consent(target):
        return
    dispatch_to_agent(target, 'mouse_scroll', {
        'deltaY': data.get('deltaY', data.get('clicks', 0))
    })

@socketio.on('desktop_key_input')
@require_participant
def handle_desktop_key_input(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None or not require_remote_consent(target):
        return
    dispatch_to_agent(target, 'key_input', {
        'type': data.get('type'), 'value': data.get('value')
    })

@socketio.on('desktop_quick_action')
@require_participant
def handle_desktop_quick_action(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None or not require_remote_consent(target):
        return
    dispatch_to_agent(target, 'quick_action', dict(data))

# Forwarding remote laser, annotation, and in-app executive commands
@socketio.on('admin_remote_pointer')
@require_participant
def handle_admin_remote_pointer(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target = data.get('target')
    if not valid_remote_target(target):
        emit_remote_error('Remote pointer target is not connected.')
        return
    if not require_remote_consent(target):
        return
    try:
        payload = {
            'x': max(0.0, min(1.0, float(data.get('x', 0)))),
            'y': max(0.0, min(1.0, float(data.get('y', 0)))),
            'active': bool(data.get('active', False)),
        }
    except (TypeError, ValueError):
        emit_remote_error('Invalid remote pointer coordinates.')
        return
    emit('client_remote_pointer', payload, to=target)

@socketio.on('admin_remote_annotate')
@require_participant
def handle_admin_remote_annotate(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target = data.get('target')
    if not valid_remote_target(target):
        emit_remote_error('Remote annotation target is not connected.')
        return
    if not require_remote_consent(target):
        return
    action = data.get('action')
    if action == 'clear':
        emit('client_remote_annotate', {'action': 'clear'}, to=target)
        return
    stroke = data.get('stroke', {})
    if (
        action != 'stroke'
        or not isinstance(stroke, dict)
        or any(
            not isinstance(stroke.get(key), (int, float))
            or not 0 <= float(stroke.get(key)) <= 1
            for key in ('x0', 'y0', 'x1', 'y1')
        )
    ):
        emit_remote_error('Invalid remote annotation payload.')
        return
    try:
        size = max(1, min(20, float(stroke.get('size', 4))))
        normalized_stroke = {
            'x0': float(stroke['x0']), 'y0': float(stroke['y0']),
            'x1': float(stroke['x1']), 'y1': float(stroke['y1']),
            'color': str(stroke.get('color', '#ff1744'))[:32],
            'size': size,
        }
    except (TypeError, ValueError):
        emit_remote_error('Invalid remote annotation values.')
        return
    emit('client_remote_annotate', {
        'action': 'stroke',
        'stroke': normalized_stroke,
    }, to=target)

@socketio.on('admin_remote_command')
@require_participant
def handle_admin_remote_command(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target = data.get('target')
    command = data.get('command')
    if not valid_remote_target(target):
        emit_remote_error('Remote command target is not connected.')
        return
    if command not in ALLOWED_REMOTE_COMMANDS:
        emit_remote_error('Unsupported remote command.')
        return
    payload = data.get('payload') if isinstance(data.get('payload'), dict) else {}
    if len(json.dumps(payload)) > 4000:
        emit_remote_error('Remote command payload is too large.')
        return
    if command == 'open_url':
        target_url = payload.get('url')
        try:
            parsed = urlparse(target_url) if isinstance(target_url, str) else None
        except ValueError:
            parsed = None
        if (
            parsed is None
            or parsed.scheme not in {'http', 'https'}
            or not parsed.netloc
            or len(target_url) > 2048
        ):
            emit_remote_error('Remote URL must be a valid HTTP(S) URL.')
            return
    if not require_remote_consent(target):
        return
    emit('client_remote_command', {
        'command': command,
        'payload': payload,
    }, to=target)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in participants:
        user = participants.pop(request.sid)
        print(f"[{user['role'].upper()}] disconnected: {user['name']} ({request.sid})")
        emit('user_left', {'id': request.sid, 'role': user['role'], 'name': user['name']}, to=ROOM_NAME)
        if user['role'] == 'client':
            emit('client_left', {'id': request.sid}, to=ROOM_NAME)

if __name__ == '__main__':
    print("Starting WeWatch WebRTC Signaling Server on port 5001...")
    socketio.run(
        app,
        debug=False,
        host=os.getenv('WEBRTC_HOST', '127.0.0.1'),
        port=5001,
        allow_unsafe_werkzeug=ALLOW_UNSAFE_WERKZEUG,
    )
