import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parent.parent


class FakeCamera:
    frame_rgb = None

    def __init__(self, *_args, **_kwargs):
        pass

    def get_frame(self):
        return None

    def register_face(self, _name):
        return True, "ok"


def fake_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class RegistrationRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_env = {
            key: os.environ.get(key)
            for key in ('WEBWATCH_USERS_DB', 'WEBWATCH_SESSION_SECRET', 'WEBRTC_ADMIN_TOKEN')
        }
        os.environ['WEBWATCH_USERS_DB'] = str(Path(self.temp.name) / 'users.db')
        os.environ['WEBWATCH_SESSION_SECRET'] = 'test-session-secret-that-is-long-enough'
        os.environ['WEBRTC_ADMIN_TOKEN'] = 'test-admin-token'

        self.previous_modules = {
            name: sys.modules.get(name)
            for name in ('camera', 'services.jarvis', 'services.database', 'services.room_auth')
        }
        sys.modules['camera'] = fake_module('camera', AICamera=FakeCamera, FEATURES={}, STATUS={})
        sys.modules['services.jarvis'] = fake_module('services.jarvis', start_jarvis=lambda _camera: None)
        sys.modules['services.database'] = fake_module(
            'services.database', init_db=lambda: None, init_attendance_db=lambda: None
        )
        sys.modules['services.room_auth'] = fake_module(
            'services.room_auth', issue_room_token=lambda *_args, **_kwargs: 'test-ticket'
        )

        spec = importlib.util.spec_from_file_location('wewatch_app_registration_test', ROOT / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.app.config.update(TESTING=True)
        self.client = self.module.app.test_client()

    def tearDown(self):
        for name, previous in self.previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def session_token(self, key):
        with self.client.session_transaction() as session:
            return session[key]

    def test_register_login_account_and_logout(self):
        self.assertEqual(self.client.get('/auth/register').status_code, 200)
        response = self.client.post(
            '/auth/register',
            data={
                'csrf_token': self.session_token('preauth_csrf_token'),
                'display_name': 'Desti Marliyana',
                'email': 'DESTI@example.com',
                'password': 'StrongPassword123',
                'password_confirmation': 'StrongPassword123',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login?registered=1', response.location)

        self.client.get('/auth/login')
        response = self.client.post(
            '/auth/login',
            data={
                'csrf_token': self.session_token('preauth_csrf_token'),
                'auth_method': 'user',
                'email': 'desti@example.com',
                'password': 'StrongPassword123',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/account'))
        self.assertEqual(self.client.get('/account').status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 302)

        response = self.client.post(
            '/auth/logout', data={'csrf_token': self.session_token('csrf_token')}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/account').status_code, 302)

    def test_invalid_csrf_and_weak_password_are_rejected(self):
        response = self.client.post(
            '/auth/register',
            data={
                'csrf_token': 'invalid',
                'display_name': 'Desti',
                'email': 'desti@example.com',
                'password': 'StrongPassword123',
                'password_confirmation': 'StrongPassword123',
            },
        )
        self.assertEqual(response.status_code, 403)

        self.client.get('/auth/register')
        response = self.client.post(
            '/auth/register',
            data={
                'csrf_token': self.session_token('preauth_csrf_token'),
                'display_name': 'Desti',
                'email': 'desti@example.com',
                'password': 'short',
                'password_confirmation': 'short',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Password minimal 12 karakter', response.data)

    def test_admin_token_path_remains_available(self):
        self.client.get('/auth/login')
        response = self.client.post(
            '/auth/login',
            data={
                'csrf_token': self.session_token('preauth_csrf_token'),
                'auth_method': 'admin',
                'token': 'test-admin-token',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/'))
        with self.client.session_transaction() as session:
            self.assertTrue(session['admin_authenticated'])
            self.assertEqual(session['role'], 'admin')


if __name__ == '__main__':
    unittest.main()
