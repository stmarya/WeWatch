"""Security/AI regressions. No webcam, real desktop actions or cloud calls."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

os.environ.setdefault('WEBRTC_SECRET_KEY', 's' * 64)
os.environ.setdefault('WEBRTC_ADMIN_TOKEN', 'admin-test')
os.environ.setdefault('WEBRTC_REQUIRE_JOIN_TOKEN', 'true')
from WebRTC_Meet import app as server
from services.room_auth import issue_room_token, verify_room_token
from core.ai_policy import select_identity
from desktop_agent import _claim_command, execute_command


class RoomSecurityTests(unittest.TestCase):
    def setUp(self):
        server.participants.clear()
        for key in ('meeting_locked', 'active_poll', 'whiteboard_history'):
            server.room_store.delete(key)
        self.connections = []

    def tearDown(self):
        for connection in self.connections:
            if connection.is_connected():
                connection.disconnect()
        server.participants.clear()

    def connect(self, identity=None, role='client'):
        client = server.socketio.test_client(server.app)
        self.connections.append(client)
        if identity:
            client.emit('join', {'role': role, 'identity': identity,
                                'join_token': issue_room_token(server.ROOM_NAME, identity, role)})
            client.get_received()
        return client

    def sid(self, identity):
        return next(sid for sid, user in server.participants.items() if user['identity'] == identity)

    def test_unjoined_events_cannot_read_or_write_room(self):
        host = self.connect('host', 'admin')
        outsider = self.connect()
        for event, payload in [('chat_message', {'text': 'injected'}), ('live_caption', {'text': 'spoof'}),
                               ('webrtc_offer', {'target': self.sid('host'), 'offer': {}}),
                               ('whiteboard_draw', {'x0': 1}), ('whiteboard_request_sync', {}),
                               ('submit_vote', {}), ('client_proctor_alert', []), ('reaction_emoji', {})]:
            outsider.emit(event, payload)
        self.assertFalse(host.get_received())
        self.assertFalse(server.room_store.get('whiteboard_history'))
        self.assertEqual(len(outsider.get_received()), 8)

    def test_sender_is_server_owned_and_bad_target_does_not_crash(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        host.get_received()
        host.emit('webrtc_offer', {'target': self.sid('alice'), 'sender': 'spoof', 'offer': {'type': 'offer'}})
        offer = next(e for e in client.get_received() if e['name'] == 'webrtc_offer')
        self.assertEqual(offer['args'][0]['sender'], self.sid('host'))
        for event in ('webrtc_offer', 'webrtc_answer', 'webrtc_ice_candidate'):
            host.emit(event, {'target': []})

    def test_consent_is_explicit_revocable_and_expiring(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        host.get_received()
        command = {'target': self.sid('alice'), 'command': 'ring_bell'}
        host.emit('admin_remote_command', command)
        self.assertFalse(client.get_received())
        client.emit('remote_assistance_consent', {'granted': True})
        client.get_received()
        host.emit('admin_remote_command', command)
        self.assertTrue(any(e['name'] == 'client_remote_command' for e in client.get_received()))
        client.emit('remote_assistance_consent', {'granted': False})
        client.get_received()
        host.emit('admin_remote_command', command)
        self.assertFalse(client.get_received())
        user = server.participants[self.sid('alice')]
        user['remote_consent_until'] = time.time() - 1
        server.participants[self.sid('alice')] = user
        self.assertFalse(server.remote_consent(self.sid('alice')))

    def test_host_cannot_grant_client_consent(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        host.emit('remote_assistance_consent', {'target': self.sid('alice'), 'granted': True})
        self.assertFalse(server.remote_consent(self.sid('alice')))
        client.emit('remote_assistance_consent', {'granted': 'true'})
        self.assertFalse(server.remote_consent(self.sid('alice')))

    def test_kick_disconnects_server_side(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        sid = self.sid('alice')
        host.emit('admin_kick_client', {'target': sid})
        self.assertFalse(client.is_connected())
        self.assertNotIn(sid, server.participants)

    def test_join_acceptance_uses_token_identity_not_display_name(self):
        client = self.connect()
        client.emit('join', {'role': 'client', 'name': 'Different Display Name',
                            'join_token': issue_room_token(server.ROOM_NAME, 'stable-id')})
        self.assertTrue(any(e['name'] == 'join_accepted' for e in client.get_received()))
        self.assertEqual(server.participants[self.sid('stable-id')]['name'], 'Different Display Name')

    def test_agent_ticket_is_bound_to_target_identity(self):
        token = issue_room_token(server.ROOM_NAME, 'device', 'agent', target_identity='alice')
        bad = self.connect()
        bad.emit('join', {'role': 'agent', 'identity': 'device', 'target_identity': 'bob', 'join_token': token})
        self.assertTrue(any(e['name'] == 'join_rejected' for e in bad.get_received()))
        good = self.connect()
        good.emit('join', {'role': 'agent', 'identity': 'device', 'target_identity': 'alice', 'join_token': token})
        self.assertTrue(any(e['name'] == 'join_accepted' for e in good.get_received()))

    def test_missing_token_configuration_is_rejected_without_crash(self):
        client = self.connect()
        with patch.dict(os.environ, {'WEBRTC_SECRET_KEY': ''}):
            client.emit('join', {'role': 'client', 'join_token': 'x.y'})
        self.assertTrue(any(e['name'] == 'join_rejected' for e in client.get_received()))

    def test_duplicate_identity_rejected(self):
        self.connect('alice')
        client = self.connect()
        client.emit('join', {'role': 'client', 'identity': 'alice',
                            'join_token': issue_room_token(server.ROOM_NAME, 'alice')})
        self.assertTrue(any(e['name'] == 'join_rejected' for e in client.get_received()))

    def test_poll_does_not_disclose_voter_mapping(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        host.emit('create_poll', {'question': 'Q?', 'options': ['A', 'B']})
        poll = next(e['args'][0] for e in client.get_received() if e['name'] == 'poll_created')
        self.assertNotIn('voters', poll)

    def test_malformed_api_and_proctor_payloads(self):
        client = server.app.test_client()
        response = client.post('/api/room-token', headers={'X-Admin-Token': 'admin-test'}, json=[])
        self.assertEqual(response.status_code, 400)
        joined = self.connect('alice')
        joined.emit('client_proctor_alert', ['invalid'])
        self.assertFalse(any(e['name'] == 'admin_proctor_alert' for e in joined.get_received()))

    def test_media_token_cannot_outlive_invitation(self):
        with patch.dict(os.environ, {'LIVEKIT_API_KEY': 'devkey', 'LIVEKIT_API_SECRET': 'k' * 32}):
            token = issue_room_token(server.ROOM_NAME, 'alice', ttl=60)
            response = server.app.test_client().post('/api/livekit-token', json={'join_token': token, 'ttl': 86400})
            self.assertEqual(response.status_code, 200)
            raw = response.json['livekit_token'].split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
            self.assertLessEqual(claims['exp'], verify_room_token(token, server.ROOM_NAME)['exp'])

    def test_locked_meeting_rejects_livekit_exchange(self):
        server.room_store.set('meeting_locked', True)
        response = server.app.test_client().post('/api/livekit-token', json={'join_token': issue_room_token(server.ROOM_NAME, 'alice')})
        self.assertEqual(response.status_code, 403)

    def test_invalid_whiteboard_does_not_enter_history(self):
        client = self.connect('alice')
        client.emit('whiteboard_draw', {'x0': 0, 'y0': 0, 'x1': 'bad', 'y1': 1})
        self.assertFalse(server.room_store.get('whiteboard_history'))
        client.emit('whiteboard_draw', {'x0': 0, 'y0': 0, 'x1': 1, 'y1': 1, 'size': 4, 'color': '#ffffff'})
        self.assertEqual(len(server.room_store.get('whiteboard_history')), 1)

    def test_client_cannot_override_host_media_permission(self):
        host = self.connect('host', 'admin')
        client = self.connect('alice')
        host.emit('update_host_permission', {'perm': 'mic', 'allowed': False})
        client.get_received()
        client.emit('toggle_media', {'type': 'mic', 'enabled': True})
        self.assertTrue(any(e['name'] == 'action_rejected' for e in client.get_received()))
        server.room_store.delete('host_permissions')

    def test_headers_do_not_leak_tokens_or_cache_pages(self):
        response = server.app.test_client().get('/')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


class AIAndAgentTests(unittest.TestCase):
    def test_multisample_same_identity_is_not_ambiguous(self):
        self.assertEqual(select_identity(['alice', 'alice', 'bob'], [0.25, 0.26, 0.6]), 'alice')
        self.assertEqual(select_identity(['alice', 'bob'], [0.25, 0.26]), 'Tidak Dikenal')
        self.assertEqual(select_identity(['alice'], [0.8]), 'Tidak Dikenal')
        self.assertEqual(select_identity([], []), 'Tidak Dikenal')
        self.assertEqual(select_identity(['alice'], [float('nan')]), 'Tidak Dikenal')

    def test_real_camera_feature_policy_without_loading_hardware(self):
        import ast
        from core.ai_policy import MODEL_REQUIREMENTS
        tree = ast.parse(Path('camera.py').read_text())
        camera = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AICamera')
        methods = [n for n in camera.body if isinstance(n, ast.FunctionDef) and n.name in {'feature_error', 'set_feature'}]
        namespace = {'os': os, 'MODEL_REQUIREMENTS': MODEL_REQUIREMENTS}
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), 'camera-policy', 'exec'), namespace)
        fake = types.SimpleNamespace(ai=types.SimpleNamespace(known_face_encodings=[], face_detector=None),
                                     running=True, status={'camera_state': 'ready'}, features={'blur': False, 'music_player': False})
        fake.feature_error = types.MethodType(namespace['feature_error'], fake)
        set_feature = types.MethodType(namespace['set_feature'], fake)
        self.assertFalse(set_feature('music_player', True)[0])
        self.assertFalse(set_feature('blur', True)[0])
        self.assertTrue(set_feature('blur', False)[0])
        self.assertFalse(set_feature('blur', 'false')[0])

    def test_nonfinite_desktop_expiry_is_rejected(self):
        for value in (float('nan'), float('inf'), time.time() + 900):
            with self.assertRaises(ValueError):
                _claim_command({'request_id': 'bad-expiry', 'expires_at': value})

    def test_native_agent_defaults_to_no_remote_control(self):
        with patch('desktop_agent.ALLOW_REMOTE_CONTROL', False):
            with self.assertRaises(PermissionError):
                execute_command('key_input', {'type': 'text', 'value': 'x'})

    def test_middle_click_uses_supported_pyautogui_api(self):
        from unittest.mock import MagicMock
        desktop = MagicMock()
        desktop.size.return_value = (100, 100)
        with patch('desktop_agent.ALLOW_REMOTE_CONTROL', True), patch('desktop_agent.pyautogui', desktop):
            execute_command('mouse_click', {'button': 'middle', 'xRatio': 0.5, 'yRatio': 0.5})
        desktop.click.assert_called_once_with(50, 50, button='middle')

    def test_legacy_face_model_adapter_resolves_installed_assets(self):
        import tempfile
        with patch.dict(sys.modules, {'face_recognition': types.SimpleNamespace()}):
            spec = importlib.util.spec_from_file_location('face_backend_test', 'core/face_backend.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'face_recognition_models/models'
            root.mkdir(parents=True)
            for filename in module.MODEL_FILES.values():
                (root / filename).write_bytes(b'fixture')
            dist = types.SimpleNamespace(version='0.3.0', locate_file=lambda path: Path(folder) / path)
            adapted = module.legacy_models_adapter(dist)
            self.assertTrue(Path(adapted.pose_predictor_model_location()).is_file())
            (root / next(iter(module.MODEL_FILES.values()))).unlink()
            with self.assertRaises(RuntimeError):
                module.legacy_models_adapter(dist)

    def test_pulse_estimator_rejects_flat_short_and_gapped_data(self):
        import numpy as np
        from utils.helpers import calculate_bpm
        times = np.arange(0, 12, 1 / 15)
        self.assertEqual(calculate_bpm(np.ones(len(times)), timestamps=times), 0)
        self.assertEqual(calculate_bpm([1, 2, 3]), 0)
        signal = 100 + np.sin(2 * np.pi * 1.2 * times)
        self.assertAlmostEqual(calculate_bpm(signal, timestamps=times), 72, delta=4)
        times[80:] += 2
        self.assertEqual(calculate_bpm(signal, timestamps=times), 0)

    def test_one_model_failure_does_not_skip_remaining_models(self):
        from unittest.mock import MagicMock
        fake_cv = MagicMock(); fake_cv.imread.return_value = None
        vision = MagicMock()
        vision.FaceLandmarker.create_from_options.side_effect = RuntimeError('missing model')
        mediapipe = types.ModuleType('mediapipe'); tasks = types.ModuleType('mediapipe.tasks')
        mp_python = types.ModuleType('mediapipe.tasks.python')
        tasks.python = mp_python; mp_python.vision = vision; mp_python.BaseOptions = MagicMock()
        with patch.dict(sys.modules, {'cv2': fake_cv, 'face_recognition': MagicMock(), 'mediapipe': mediapipe,
                                     'mediapipe.tasks': tasks, 'mediapipe.tasks.python': mp_python,
                                     'core.face_backend': types.SimpleNamespace(face_recognition=types.SimpleNamespace(load_image_file=lambda *a: None, face_encodings=lambda *a, **k: []))}):
            spec = importlib.util.spec_from_file_location('models_under_test', 'core/ai_models.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            models = module.AIModelManager()
            self.assertIsNone(models.face_detector)
            self.assertIsNotNone(models.object_detector)
            self.assertEqual(models.model_health['face_detector'], 'unavailable')
            self.assertEqual(models.model_health['object_detector'], 'ready')


if __name__ == '__main__':
    unittest.main()
