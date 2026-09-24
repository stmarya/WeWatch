import os
import threading
import subprocess
import ctypes
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('WEBRTC_SECRET_KEY', os.urandom(32).hex())
socketio = SocketIO(
    app,
    cors_allowed_origins=os.getenv('WEBRTC_ALLOWED_ORIGINS', 'http://localhost:5001'),
)

# In-memory store for connected users: { sid: { id, name, role, mic, cam, hand, joined_at } }
participants = {}
meeting_locked = False
whiteboard_history = []
active_poll = None
host_permissions = {
    'screen': True,
    'chat': True,
    'mic': True,
    'video': True
}
ADMIN_TOKEN = os.getenv('WEBRTC_ADMIN_TOKEN', '').strip()


def is_admin(sid):
    return participants.get(sid, {}).get('role') == 'admin'


def require_admin():
    if not is_admin(request.sid):
        emit('action_rejected', {'reason': 'Host permission required.'}, to=request.sid)
        return False
    return True

@app.route('/')
@app.route('/client')
def client_page():
    return render_template('client.html')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

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
    global meeting_locked
    requested_role = data.get('role', 'client')
    if requested_role == 'admin':
        if not ADMIN_TOKEN or data.get('token', '') != ADMIN_TOKEN:
            emit('join_rejected', {'reason': 'Admin token required.'})
            return
    role = 'admin' if requested_role == 'admin' else 'client'
    
    if meeting_locked and role == 'client':
        emit('join_rejected', {'reason': 'This meeting has been locked by the host.'})
        return

    name = data.get('name', 'Admin (Host)' if role == 'admin' else f'Participant {request.sid[:4]}')
    room = 'gmeet_room'
    join_room(room)
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    participants[request.sid] = {
        'id': request.sid,
        'name': name,
        'role': role,
        'mic': data.get('mic', True),
        'cam': data.get('cam', True),
        'hand': False,
        'joined_at': now_str
    }
    print(f"[{role.upper()}] joined: {name} ({request.sid}) at {now_str}")
    
    # Send current participant list, lock state, and host permissions to newly joined user
    emit('participants_update', list(participants.values()))
    emit('meeting_lock_changed', {'locked': meeting_locked})
    emit('host_permissions_update', host_permissions)
    if active_poll:
        emit('poll_created', active_poll)
    
    # Broadcast to other participants
    emit('user_joined', participants[request.sid], to=room, include_self=False)
    
    # Specifically inform admin of client joined for WebRTC peering
    if role == 'client':
        emit('client_joined', {'id': request.sid, 'name': name}, to=room)

@socketio.on('webrtc_offer')
def handle_offer(data):
    target = data.get('target')
    if target in participants:
        emit('webrtc_offer', data, to=target)

@socketio.on('webrtc_answer')
def handle_answer(data):
    target = data.get('target')
    if target in participants:
        emit('webrtc_answer', data, to=target)

@socketio.on('webrtc_ice_candidate')
def handle_ice(data):
    target = data.get('target')
    if target in participants:
        emit('webrtc_ice_candidate', data, to=target)

@socketio.on('chat_message')
def handle_chat_message(data):
    user = participants.get(request.sid, {})
    if user.get('role') == 'client' and not host_permissions.get('chat', True):
        emit('chat_rejected', {'reason': 'Chat has been disabled by the meeting host.'})
        return

    message_payload = {
        'senderId': request.sid,
        'senderName': user.get('name', data.get('name', 'User')),
        'senderRole': user.get('role', 'client'),
        'text': str(data.get('text', ''))[:2000],
        'time': datetime.now().strftime('%I:%M %p')
    }
    emit('chat_message', message_payload, to='gmeet_room')

@socketio.on('live_caption')
def handle_live_caption(data):
    # Broadcast live speech transcript to everyone in call
    emit('caption_broadcast', data, to='gmeet_room')

@socketio.on('update_host_permission')
def handle_update_host_permission(data):
    if not require_admin():
        return
    perm = data.get('perm')
    allowed = data.get('allowed', True)
    if perm in host_permissions:
        host_permissions[perm] = allowed
        print(f"[SECURITY] Host permission '{perm}' set to: {allowed}")
        emit('host_permissions_update', host_permissions, to='gmeet_room')

@socketio.on('toggle_media')
def handle_toggle_media(data):
    if request.sid in participants:
        media_type = data.get('type') # 'mic' or 'cam'
        if media_type not in ('mic', 'cam'):
            return
        enabled = bool(data.get('enabled', True))
        participants[request.sid][media_type] = enabled
        emit('user_media_toggled', {
            'id': request.sid,
            'type': media_type,
            'enabled': enabled
        }, to='gmeet_room')

@socketio.on('raise_hand')
def handle_raise_hand(data):
    if request.sid in participants:
        raised = data.get('raised', False)
        participants[request.sid]['hand'] = raised
        emit('user_hand_raised', {
            'id': request.sid,
            'name': participants[request.sid]['name'],
            'raised': raised
        }, to='gmeet_room')

@socketio.on('reaction_emoji')
def handle_reaction(data):
    emit('reaction_emoji', {
        'senderId': request.sid,
        'emoji': data.get('emoji', '👍')
    }, to='gmeet_room')

@socketio.on('recording_state')
def handle_recording_state(data):
    emit('recording_state', {
        'isRecording': data.get('isRecording', False)
    }, to='gmeet_room')

# Host-specific moderation events
@socketio.on('admin_mute_client')
def handle_mute_client(data):
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id in participants:
        participants[target_id]['mic'] = False
        emit('force_mute', {}, to=target_id)
        emit('user_media_toggled', {'id': target_id, 'type': 'mic', 'enabled': False}, to='gmeet_room')

@socketio.on('admin_mute_all')
def handle_mute_all():
    if not require_admin():
        return
    for sid, u in participants.items():
        if u['role'] == 'client':
            u['mic'] = False
            emit('force_mute', {}, to=sid)
            emit('user_media_toggled', {'id': sid, 'type': 'mic', 'enabled': False}, to='gmeet_room')

@socketio.on('admin_kick_client')
def handle_kick_client(data):
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id in participants:
        emit('force_disconnect', {'reason': 'You were removed by the meeting host.'}, to=target_id)

@socketio.on('admin_end_all')
def handle_end_all():
    if not require_admin():
        return
    emit('meeting_ended_by_host', {'reason': 'The meeting was ended for everyone by the host.'}, to='gmeet_room')

# Meeting Lock Security
@socketio.on('toggle_meeting_lock')
def handle_toggle_meeting_lock(data):
    if not require_admin():
        return
    global meeting_locked
    meeting_locked = data.get('locked', False)
    print(f"[SECURITY] Meeting locked state: {meeting_locked}")
    emit('meeting_lock_changed', {'locked': meeting_locked}, to='gmeet_room')

# Collaborative Whiteboard Events
@socketio.on('whiteboard_draw')
def handle_whiteboard_draw(data):
    if len(whiteboard_history) > 2000:
        whiteboard_history.pop(0)
    whiteboard_history.append(data)
    emit('whiteboard_draw', data, to='gmeet_room', include_self=False)

@socketio.on('whiteboard_clear')
def handle_whiteboard_clear():
    global whiteboard_history
    whiteboard_history = []
    emit('whiteboard_clear', {}, to='gmeet_room')

@socketio.on('whiteboard_request_sync')
def handle_whiteboard_sync():
    emit('whiteboard_full_sync', {'strokes': whiteboard_history})

# In-Meeting Live Polls Events
@socketio.on('create_poll')
def handle_create_poll(data):
    if not require_admin():
        return
    global active_poll
    question = data.get('question', '').strip()
    options = data.get('options', [])
    if not question or not options:
        return
    
    poll_id = f"poll_{int(datetime.now().timestamp())}"
    active_poll = {
        'id': poll_id,
        'question': question,
        'options': [{'text': opt, 'votes': 0} for opt in options],
        'voters': {}, # sid -> optionIndex
        'active': True,
        'creator': participants.get(request.sid, {}).get('name', 'Host')
    }
    print(f"[POLL] Created: {question} with {len(options)} options")
    emit('poll_created', active_poll, to='gmeet_room')

@socketio.on('submit_vote')
def handle_submit_vote(data):
    global active_poll
    if not active_poll or not active_poll.get('active'):
        return
    
    poll_id = data.get('pollId')
    option_idx = data.get('optionIndex')
    if active_poll['id'] != poll_id:
        return
    if not isinstance(option_idx, int) or not 0 <= option_idx < len(active_poll['options']):
        emit('poll_error', {'reason': 'Invalid poll option.'}, to=request.sid)
        return
    
    # If user already voted, update vote or ignore
    if request.sid in active_poll['voters']:
        prev_idx = active_poll['voters'][request.sid]
        if prev_idx == option_idx:
            return
        active_poll['options'][prev_idx]['votes'] = max(0, active_poll['options'][prev_idx]['votes'] - 1)
    
    active_poll['voters'][request.sid] = option_idx
    active_poll['options'][option_idx]['votes'] += 1
    
    emit('poll_updated', {
        'id': active_poll['id'],
        'options': active_poll['options'],
        'totalVotes': len(active_poll['voters'])
    }, to='gmeet_room')

@socketio.on('end_poll')
def handle_end_poll(data):
    if not require_admin():
        return
    global active_poll
    if active_poll:
        active_poll['active'] = False
        emit('poll_ended', {'id': active_poll['id']}, to='gmeet_room')

# =========================================================================
# HOST REMOTE CONTROL & PROCTORING EVENTS
# =========================================================================

@socketio.on('admin_remote_command')
def handle_remote_command(data):
    if not require_admin():
        return
    target_id = data.get('target')
    command = data.get('command')
    payload = data.get('payload', {})
    print(f"[REMOTE CONTROL] Command '{command}' to {target_id}")
    if target_id == 'all':
        emit('remote_command_received', {'command': command, 'payload': payload, 'from': request.sid}, to='gmeet_room')
    elif target_id in participants:
        emit('remote_command_received', {'command': command, 'payload': payload, 'from': request.sid}, to=target_id)

@socketio.on('admin_remote_pointer')
def handle_remote_pointer(data):
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id == 'all':
        emit('remote_pointer_moved', data, to='gmeet_room', include_self=False)
    elif target_id in participants:
        emit('remote_pointer_moved', data, to=target_id)

@socketio.on('admin_remote_annotate')
def handle_remote_annotate(data):
    if not require_admin():
        return
    target_id = data.get('target')
    if target_id == 'all':
        emit('remote_annotation_received', data, to='gmeet_room', include_self=False)
    elif target_id in participants:
        emit('remote_annotation_received', data, to=target_id)

@socketio.on('client_proctor_alert')
def handle_proctor_alert(data):
    user = participants.get(request.sid, {})
    emit('admin_proctor_alert', {
        'id': request.sid,
        'name': user.get('name', 'Participant'),
        'event': data.get('event'),
        'time': datetime.now().strftime('%H:%M:%S')
    }, to='gmeet_room')

# =========================================================================
# OS-LEVEL REMOTE DESKTOP CONTROL (HR & MANAGER TAKEOVER)
# =========================================================================

@socketio.on('desktop_mouse_move')
def handle_desktop_mouse_move(data):
    if not require_admin():
        return
    if not pyautogui:
        return
    try:
        sw, sh = pyautogui.size()
        tx = max(0, min(sw - 1, int(data['xRatio'] * sw)))
        ty = max(0, min(sh - 1, int(data['yRatio'] * sh)))
        pyautogui.moveTo(tx, ty)
    except Exception as e:
        print("[DESKTOP MOUSE MOVE ERROR]", e)

@socketio.on('desktop_mouse_click')
def handle_desktop_mouse_click(data):
    if not require_admin():
        return
    if not pyautogui:
        return
    try:
        sw, sh = pyautogui.size()
        tx = max(0, min(sw - 1, int(data['xRatio'] * sw)))
        ty = max(0, min(sh - 1, int(data['yRatio'] * sh)))
        btn = data.get('button', 'left')
        if btn == 'right':
            pyautogui.rightClick(tx, ty)
        elif btn == 'double':
            pyautogui.doubleClick(tx, ty)
        elif btn == 'middle':
            pyautogui.middleClick(tx, ty)
        else:
            pyautogui.click(tx, ty)
        print(f"[DESKTOP CLICK] {btn} at ({tx}, {ty})")
    except Exception as e:
        print("[DESKTOP CLICK ERROR]", e)

@socketio.on('desktop_mouse_scroll')
def handle_desktop_mouse_scroll(data):
    if not require_admin():
        return
    if not pyautogui:
        return
    try:
        clicks = int(data.get('clicks', -120))
        pyautogui.scroll(clicks)
    except Exception as e:
        print("[DESKTOP SCROLL ERROR]", e)

@socketio.on('desktop_key_input')
def handle_desktop_key_input(data):
    if not require_admin():
        return
    if not pyautogui:
        emit('desktop_action_result', {'status': 'error', 'msg': 'pyautogui not available on server'}, to=request.sid)
        return
    try:
        itype = data.get('type')
        val = data.get('value')
        if itype == 'text':
            pyautogui.write(val, interval=0.005)
            emit('desktop_action_result', {'status': 'success', 'msg': f'Typed "{val}" on client desktop'}, to=request.sid)
        elif itype == 'key':
            pyautogui.press(val)
            emit('desktop_action_result', {'status': 'success', 'msg': f'Pressed [{val}]'}, to=request.sid)
        elif itype == 'hotkey':
            keys = val if isinstance(val, list) else val.split('+')
            pyautogui.hotkey(*keys)
            emit('desktop_action_result', {'status': 'success', 'msg': f'Triggered hotkey [{" + ".join(keys)}]'}, to=request.sid)
        print(f"[DESKTOP KEY] {itype}: {val}")
    except Exception as e:
        print("[DESKTOP KEY ERROR]", e)
        emit('desktop_action_result', {'status': 'error', 'msg': str(e)}, to=request.sid)

@socketio.on('desktop_quick_action')
def handle_desktop_quick_action(data):
    if not require_admin():
        return
    action = data.get('action')
    print(f"[HR DESKTOP ACTION] {action}")
    try:
        if action == 'lock_workstation':
            ctypes.windll.user32.LockWorkStation()
            emit('desktop_action_result', {'status': 'success', 'msg': 'Client Windows workstation locked!'}, to=request.sid)
        elif action == 'show_desktop':
            if pyautogui:
                pyautogui.hotkey('win', 'd')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Show Desktop executed (Win + D)'}, to=request.sid)
        elif action == 'open_task_manager':
            if pyautogui:
                pyautogui.hotkey('ctrl', 'shift', 'esc')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Task Manager launched on client desktop'}, to=request.sid)
        elif action == 'open_explorer':
            if pyautogui:
                pyautogui.hotkey('win', 'e')
            emit('desktop_action_result', {'status': 'success', 'msg': 'File Explorer opened (Win + E)'}, to=request.sid)
        elif action == 'close_active_window':
            if pyautogui:
                pyautogui.hotkey('alt', 'f4')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Active window closed (Alt + F4)'}, to=request.sid)
        elif action == 'volume_up':
            if pyautogui:
                for _ in range(3):
                    pyautogui.press('volumeup')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Master volume increased (+6%)'}, to=request.sid)
        elif action == 'volume_down':
            if pyautogui:
                for _ in range(3):
                    pyautogui.press('volumedown')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Master volume decreased (-6%)'}, to=request.sid)
        elif action == 'volume_mute':
            if pyautogui:
                pyautogui.press('volumemute')
            emit('desktop_action_result', {'status': 'success', 'msg': 'Client audio mute toggled'}, to=request.sid)
        elif action == 'open_url':
            import webbrowser
            target_url = (data.get('url') or 'https://google.com').strip()
            if not target_url.startswith(('http://', 'https://')):
                target_url = 'https://' + target_url
            webbrowser.open(target_url)
            emit('desktop_action_result', {'status': 'success', 'msg': f'Opened URL in client browser: {target_url}'}, to=request.sid)
        elif action == 'clipboard_inject':
            clip_text = data.get('text', '').strip()
            if clip_text:
                subprocess.run(['powershell', '-Command', f"Set-Clipboard -Value '{clip_text}'"], capture_output=True)
                emit('desktop_action_result', {'status': 'success', 'msg': f'Copied text into client clipboard: "{clip_text}"'}, to=request.sid)
            else:
                emit('desktop_action_result', {'status': 'error', 'msg': 'Clipboard text cannot be empty'}, to=request.sid)
        elif action == 'capture_screen':
            if pyautogui:
                import io, base64
                screenshot = pyautogui.screenshot()
                # Resize thumbnail for fast transmission
                screenshot.thumbnail((1280, 720))
                buffered = io.BytesIO()
                screenshot.save(buffered, format="JPEG", quality=65)
                img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                emit('desktop_screenshot_data', {'b64': img_b64}, to=request.sid)
                emit('desktop_action_result', {'status': 'success', 'msg': 'Desktop screenshot captured!'}, to=request.sid)
        elif action == 'system_telemetry':
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total_ram_gb = round(stat.ullTotalPhys / (1024**3), 1)
            avail_ram_gb = round(stat.ullAvailPhys / (1024**3), 1)
            emit('desktop_action_result', {
                'status': 'success',
                'msg': f'Client RAM: {stat.dwMemoryLoad}% used ({avail_ram_gb}GB free of {total_ram_gb}GB)'
            }, to=request.sid)
        elif action == 'windows_alert':
            msg = data.get('message', 'Perhatian: Aktivitas Anda sedang dipantau oleh HR & Manager.')
            def popup():
                ctypes.windll.user32.MessageBoxW(0, msg, "HR & Manager Compliance Alert", 0x40000 | 0x30)
            threading.Thread(target=popup, daemon=True).start()
            emit('desktop_action_result', {'status': 'success', 'msg': 'Pop-up alert shown on client desktop!'}, to=request.sid)
        elif action == 'kill_distracting_app':
            app_name = data.get('appName', '').strip()
            if app_name:
                if not app_name.lower().endswith('.exe'):
                    app_name += '.exe'
                res = subprocess.run(['taskkill', '/F', '/IM', app_name], capture_output=True, text=True)
                if res.returncode == 0:
                    emit('desktop_action_result', {'status': 'success', 'msg': f'Process "{app_name}" successfully terminated!'}, to=request.sid)
                else:
                    emit('desktop_action_result', {'status': 'error', 'msg': f'Process "{app_name}" not found or already closed.'}, to=request.sid)
            else:
                emit('desktop_action_result', {'status': 'error', 'msg': 'Please specify process name (e.g. discord.exe)'}, to=request.sid)
    except Exception as e:
        emit('desktop_action_result', {'status': 'error', 'msg': str(e)}, to=request.sid)

# Forwarding remote laser, annotation, and in-app executive commands
@socketio.on('admin_remote_pointer')
def handle_admin_remote_pointer(data):
    if not require_admin():
        return
    target = data.get('target')
    if target:
        emit('client_remote_pointer', data, to=target)
        emit('remote_pointer_moved', data, to=target)

@socketio.on('admin_remote_annotate')
def handle_admin_remote_annotate(data):
    if not require_admin():
        return
    target = data.get('target')
    if target:
        emit('client_remote_annotate', data, to=target)
        emit('remote_annotation_received', data, to=target)

@socketio.on('admin_remote_command')
def handle_admin_remote_command(data):
    if not require_admin():
        return
    target = data.get('target')
    if target:
        emit('client_remote_command', data, to=target)
        emit('remote_command_received', data, to=target)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in participants:
        user = participants.pop(request.sid)
        print(f"[{user['role'].upper()}] disconnected: {user['name']} ({request.sid})")
        emit('user_left', {'id': request.sid, 'role': user['role'], 'name': user['name']}, to='gmeet_room')
        if user['role'] == 'client':
            emit('client_left', {'id': request.sid}, to='gmeet_room')

if __name__ == '__main__':
    print("Starting Google Meet WebRTC Signaling Server on port 5001...")
    socketio.run(app, debug=False, host='0.0.0.0', port=5001)
