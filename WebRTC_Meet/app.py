import os
import logging
import sys
import json
import uuid
import hmac
import time
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room
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
REQUIRE_JOIN_TOKEN = os.getenv('WEBRTC_REQUIRE_JOIN_TOKEN', 'false').lower() == 'true'
REQUIRE_SHARED_STATE = os.getenv('WEBRTC_REQUIRE_SHARED_STATE', 'false').lower() == 'true'
ROOM_NAME = os.getenv('WEBRTC_ROOM_NAME', 'gmeet_room')
LIVEKIT_URL = os.getenv('LIVEKIT_URL', 'ws://localhost:7880').strip()
ALLOW_UNSAFE_WERKZEUG = os.getenv(
    'WEBRTC_ALLOW_UNSAFE_WERKZEUG', 'true'
).lower() == 'true'
try:
    MAX_PARTICIPANTS = max(1, int(os.getenv('WEBRTC_MAX_PARTICIPANTS', '600')))
except ValueError:
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
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
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
    if request.headers.get('X-Admin-Token', '') != ADMIN_TOKEN or not ADMIN_TOKEN:
        return jsonify(error='admin authentication required'), 401
    data = request.get_json(silent=True) or {}
    identity = str(data.get('identity', '')).strip()
    role = str(data.get('role', 'client')).strip()
    room = str(data.get('room', ROOM_NAME)).strip() or ROOM_NAME
    if not identity or role not in {'admin', 'client', 'agent'}:
        return jsonify(error='identity and valid role are required'), 400
    if room != ROOM_NAME:
        return jsonify(error='room does not match the configured signaling room'), 400
    try:
        ttl = int(data.get('ttl', 3600))
        join_token = issue_room_token(room, identity, role, ttl)
    except (ValueError, RuntimeError) as exc:
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
        ttl = int(data.get('ttl', 3600))
        token = issue_livekit_token(ROOM_NAME, claims['identity'], ttl)
    except (ValueError, RuntimeError, KeyError) as exc:
        return jsonify(error=str(exc)), 401
    return jsonify(
        livekit_token=token,
        livekit_url=LIVEKIT_URL,
        room=ROOM_NAME,
        identity=claims['identity'],
        role=claims['role'],
    )


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
        "short_name": "Google Meet",
        "name": "Google Meet Client",
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
    requested_role = data.get('role', 'client')
    identity = str(data.get('identity', request.sid[:12])).strip()[:128]
    if requested_role == 'agent':
        static_agent_ok = bool(DESKTOP_AGENT_TOKEN) and hmac.compare_digest(
            str(data.get('agent_token', '')), DESKTOP_AGENT_TOKEN
        )
        ticket_ok = False
        if not static_agent_ok:
            try:
                claims = verify_room_token(data.get('join_token', ''), ROOM_NAME, identity)
                ticket_ok = claims['role'] == 'agent'
            except ValueError:
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
            except ValueError:
                ticket_ok = False
        if not (static_token_ok or ticket_ok):
            emit('join_rejected', {'reason': 'Admin token required.'})
            return
    role = requested_role if requested_role in {'admin', 'agent'} else 'client'
    if REQUIRE_JOIN_TOKEN and role == 'client':
        try:
            claims = verify_room_token(data.get('join_token', ''), ROOM_NAME, identity)
            if claims['role'] != 'client':
                raise ValueError('role mismatch')
        except ValueError:
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

    name = data.get('name', 'Admin (Host)' if role == 'admin' else f'Participant {request.sid[:4]}')
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
    print(f"[{role.upper()}] joined: {name} ({request.sid}) at {now_str}")
    
    # Send current participant list, lock state, and host permissions to newly joined user
    emit('participants_update', public_participants())
    emit('meeting_lock_changed', {'locked': is_meeting_locked()})
    emit('host_permissions_update', get_host_permissions())
    active_poll = get_active_poll()
    if active_poll:
        emit('poll_created', active_poll)
    
    # Broadcast to other participants
    if role != 'agent':
        emit('user_joined', participants[request.sid], to=room, include_self=False)
    
    # Specifically inform admin of client joined for WebRTC peering
    if role == 'client':
        emit('client_joined', {'id': request.sid, 'name': name}, to=room)


@socketio.on('presence_ping')
def handle_presence_ping():
    if request.sid in participants:
        participants.refresh(request.sid)


@socketio.on('agent_action_result')
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
    result = {
        'status': 'success' if data.get('ok') else 'error',
        'msg': str(data.get('message', 'Desktop agent completed the request.'))[:1000],
    }
    emit('desktop_action_result', result, to=reply_to)
    screenshot = data.get('screenshot_b64')
    if isinstance(screenshot, str) and len(screenshot) <= 8_000_000:
        emit('desktop_screenshot_data', {'b64': screenshot}, to=reply_to)

@socketio.on('webrtc_offer')
def handle_offer(data):
    data = _as_dict(data)
    target = data.get('target')
    if target in participants:
        emit('webrtc_offer', data, to=target)

@socketio.on('webrtc_answer')
def handle_answer(data):
    data = _as_dict(data)
    target = data.get('target')
    if target in participants:
        emit('webrtc_answer', data, to=target)

@socketio.on('webrtc_ice_candidate')
def handle_ice(data):
    data = _as_dict(data)
    target = data.get('target')
    if target in participants:
        emit('webrtc_ice_candidate', data, to=target)

@socketio.on('chat_message')
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
def handle_toggle_media(data):
    data = _as_dict(data)
    if request.sid in participants:
        media_type = data.get('type') # 'mic' or 'cam'
        if media_type not in ('mic', 'cam', 'screen'):
            return
        enabled = bool(data.get('enabled', True))
        participants[request.sid][media_type] = enabled
        emit('user_media_toggled', {
            'id': request.sid,
            'type': media_type,
            'enabled': enabled
        }, to=ROOM_NAME)

@socketio.on('raise_hand')
def handle_raise_hand(data):
    data = _as_dict(data)
    if request.sid in participants:
        raised = data.get('raised', False)
        participants[request.sid]['hand'] = raised
        emit('user_hand_raised', {
            'id': request.sid,
            'name': participants[request.sid]['name'],
            'raised': raised
        }, to=ROOM_NAME)

@socketio.on('reaction_emoji')
def handle_reaction(data):
    data = _as_dict(data)
    allowed = {'👍', '👏', '❤️', '😂', '😮', '😢', '🎉'}
    emoji = data.get('emoji', '👍')
    emit('reaction_emoji', {
        'senderId': request.sid,
        'emoji': emoji if emoji in allowed else '👍'
    }, to=ROOM_NAME)

@socketio.on('recording_state')
def handle_recording_state(data):
    data = _as_dict(data)
    if not require_admin():
        return
    emit('recording_state', {
        'isRecording': bool(data.get('isRecording', False))
    }, to=ROOM_NAME)

# Host-specific moderation events
@socketio.on('admin_mute_client')
def handle_mute_client(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id in participants:
        participants[target_id]['mic'] = False
        emit('force_mute', {}, to=target_id)
        emit('user_media_toggled', {'id': target_id, 'type': 'mic', 'enabled': False}, to=ROOM_NAME)

@socketio.on('admin_mute_all')
def handle_mute_all():
    if not require_admin():
        return
    for sid, u in participants.items():
        if u['role'] == 'client':
            u['mic'] = False
            emit('force_mute', {}, to=sid)
            emit('user_media_toggled', {'id': sid, 'type': 'mic', 'enabled': False}, to=ROOM_NAME)

@socketio.on('admin_kick_client')
def handle_kick_client(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id in participants:
        emit('force_disconnect', {'reason': 'You were removed by the meeting host.'}, to=target_id)

@socketio.on('admin_end_all')
def handle_end_all():
    if not require_admin():
        return
    emit('meeting_ended_by_host', {'reason': 'The meeting was ended for everyone by the host.'}, to=ROOM_NAME)

# Meeting Lock Security
@socketio.on('toggle_meeting_lock')
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
def handle_whiteboard_draw(data):
    if not allow_socket_event('whiteboard'):
        return
    if not isinstance(data, dict) or len(json.dumps(data)) > 10000:
        return
    def append_stroke(history):
        history = history if isinstance(history, list) else []
        return (history + [data])[-2000:]

    room_store.update('whiteboard_history', append_stroke, default=[], ttl=86400)
    emit('whiteboard_draw', data, to=ROOM_NAME, include_self=False)

@socketio.on('whiteboard_clear')
def handle_whiteboard_clear():
    if not require_admin():
        return
    room_store.set('whiteboard_history', [])
    emit('whiteboard_clear', {}, to=ROOM_NAME)

@socketio.on('whiteboard_request_sync')
def handle_whiteboard_sync():
    emit('whiteboard_full_sync', {'strokes': get_whiteboard_history()})

# In-Meeting Live Polls Events
@socketio.on('create_poll')
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
    emit('poll_created', active_poll, to=ROOM_NAME)

@socketio.on('submit_vote')
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
        previous = voters.get(request.sid)
        if previous == option_idx:
            return current
        if isinstance(previous, int) and 0 <= previous < len(current['options']):
            current['options'][previous]['votes'] = max(
                0, int(current['options'][previous].get('votes', 0)) - 1
            )
        voters[request.sid] = option_idx
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
def handle_proctor_alert(data):
    user = participants.get(request.sid, {})
    event = str((data or {}).get('event', 'unknown'))[:200]
    emit('admin_proctor_alert', {
        'id': request.sid,
        'name': user.get('name', 'Participant'),
        'event': event,
        'time': datetime.now().strftime('%H:%M:%S')
    }, to=ROOM_NAME)


@socketio.on('client_proctor_event')
def handle_proctor_event(data):
    handle_proctor_alert(data)


# =========================================================================
# OS-LEVEL REMOTE DESKTOP CONTROL (HR & MANAGER TAKEOVER)
# =========================================================================

@socketio.on('desktop_mouse_move')
def handle_desktop_mouse_move(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None:
        return
    dispatch_to_agent(target, 'mouse_move', {
        'xRatio': data.get('xRatio', 0), 'yRatio': data.get('yRatio', 0)
    })

@socketio.on('desktop_mouse_click')
def handle_desktop_mouse_click(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None:
        return
    dispatch_to_agent(target, 'mouse_click', {
        'xRatio': data.get('xRatio', 0), 'yRatio': data.get('yRatio', 0),
        'button': data.get('button', 'left')
    })

@socketio.on('desktop_mouse_scroll')
def handle_desktop_mouse_scroll(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None:
        return
    dispatch_to_agent(target, 'mouse_scroll', {
        'deltaY': data.get('deltaY', data.get('clicks', 0))
    })

@socketio.on('desktop_key_input')
def handle_desktop_key_input(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None:
        return
    dispatch_to_agent(target, 'key_input', {
        'type': data.get('type'), 'value': data.get('value')
    })

@socketio.on('desktop_quick_action')
def handle_desktop_quick_action(data):
    data = _as_dict(data)
    if not require_admin():
        return
    if not allow_socket_event('desktop'):
        return
    target = require_remote_client_target(data)
    if target is None:
        return
    dispatch_to_agent(target, 'quick_action', dict(data))

# Forwarding remote laser, annotation, and in-app executive commands
@socketio.on('admin_remote_pointer')
def handle_admin_remote_pointer(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target = data.get('target')
    if not valid_remote_target(target):
        emit_remote_error('Remote pointer target is not connected.')
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
def handle_admin_remote_annotate(data):
    data = _as_dict(data)
    if not require_admin():
        return
    target = data.get('target')
    if not valid_remote_target(target):
        emit_remote_error('Remote annotation target is not connected.')
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
        parsed = urlparse(target_url) if isinstance(target_url, str) else None
        if (
            parsed is None
            or parsed.scheme not in {'http', 'https'}
            or not parsed.netloc
            or len(target_url) > 2048
        ):
            emit_remote_error('Remote URL must be a valid HTTP(S) URL.')
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
    print("Starting Google Meet WebRTC Signaling Server on port 5001...")
    socketio.run(
        app,
        debug=False,
        host='0.0.0.0',
        port=5001,
        allow_unsafe_werkzeug=ALLOW_UNSAFE_WERKZEUG,
    )
