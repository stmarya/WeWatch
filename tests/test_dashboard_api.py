"""Dashboard HTTP contract with fake camera: not a hardware integration test."""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def load_dashboard():
    tree = ast.parse(Path('camera.py').read_text())
    constants = {node.targets[0].id: ast.literal_eval(node.value)
                 for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {'FEATURES', 'STATUS'}}
    fake = types.ModuleType('camera')
    fake.FEATURES = constants['FEATURES']; fake.STATUS = constants['STATUS']
    class Camera:
        frame_rgb = None
        def __init__(self, features, status):
            self.features = features
            self.status = status
            self.ai = types.SimpleNamespace(model_health={'face_detector': 'unavailable'})
        def feature_error(self, key):
            return 'unavailable' if key in {'mouse', 'music_player', 'blur'} else None
        def set_feature(self, key, state):
            if state and self.feature_error(key):
                return False, self.feature_error(key)
            self.features[key] = state
            return True, 'updated'
        def register_face(self, name):
            return False, 'No camera'
    fake.AICamera = Camera
    jarvis = types.ModuleType('services.jarvis'); jarvis.start_jarvis = lambda camera: None
    with patch.dict(sys.modules, {'camera': fake, 'services.jarvis': jarvis}), patch.dict(os.environ, {'WEBWATCH_SESSION_SECRET': 'a'*64, 'WEBRTC_ADMIN_TOKEN': 'admin-test'}):
        spec = importlib.util.spec_from_file_location('dashboard_test_app', 'app.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load_dashboard()

    def setUp(self):
        self.client = self.dashboard.app.test_client()

    def login(self):
        self.assertEqual(self.client.post('/auth/login', data={'token': 'admin-test'}).status_code, 302)
        with self.client.session_transaction() as session:
            return {'X-CSRF-Token': session['csrf_token']}

    def test_auth_gallery_and_csrf_logout(self):
        self.assertEqual(self.client.get('/static/gallery/secret.jpg').status_code, 401)
        headers = self.login()
        self.assertEqual(self.client.post('/auth/logout').status_code, 403)
        self.assertEqual(self.client.post('/auth/logout', headers=headers).status_code, 302)
        self.assertEqual(self.client.get('/status_data').status_code, 401)

    def test_feature_requires_boolean_object_and_available_model(self):
        headers = self.login()
        for data in ([], {'feature': ['blur'], 'state': True}, {'feature': 'blur', 'state': 'false'}):
            self.assertEqual(self.client.post('/toggle', json=data, headers=headers).status_code, 400)
        self.assertEqual(self.client.post('/toggle', json={'feature': 'blur', 'state': True}, headers=headers).status_code, 422)
        self.assertEqual(self.client.post('/toggle', json={'feature': 'blur', 'state': False}, headers=headers).status_code, 200)

    def test_face_name_requires_bounded_string(self):
        headers = self.login()
        for data in ([], {'name': []}, {'name': ''}, {'name': 'x'*65}):
            self.assertEqual(self.client.post('/snap_face', json=data, headers=headers).status_code, 400)

    def test_dashboard_no_cache_and_capabilities(self):
        self.login()
        response = self.client.get('/status_data')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('feature_errors', response.json)
        self.assertEqual(response.json['model_health']['face_detector'], 'unavailable')

if __name__ == '__main__':
    unittest.main()
