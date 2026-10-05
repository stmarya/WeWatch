import sqlite3
import tempfile
from pathlib import Path
import unittest

from services.avatars import AVATARS, avatar_url, default_avatar_for, is_valid_avatar
from services.user_store import (
    DuplicateEmailError, InvalidCurrentPasswordError, UserStore, verify_password,
)
from tests import test_auth_registration as registration_tests


PASSWORD = "StrongPassword123"


class AvatarCatalogTests(unittest.TestCase):
    def test_catalog_contains_only_bundled_svgs(self):
        self.assertGreaterEqual(len(AVATARS), 20)
        for avatar in AVATARS:
            self.assertTrue(avatar.url.startswith("/static/avatars/"))
            self.assertTrue(avatar.url.endswith(".svg"))

    def test_unknown_or_path_like_ids_are_rejected(self):
        self.assertFalse(is_valid_avatar("../app"))
        self.assertFalse(is_valid_avatar("https://evil.example/x.svg"))
        self.assertFalse(is_valid_avatar(""))
        self.assertTrue(is_valid_avatar(AVATARS[0].id))

    def test_default_avatar_is_stable(self):
        self.assertEqual(default_avatar_for("user-1"), default_avatar_for("user-1"))
        self.assertTrue(avatar_url(None, "user-1").startswith("/static/avatars/"))


class UserProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = UserStore(Path(self.temp.name) / "users.db")
        self.user = self.store.create_user("Desti", "desti@example.com", PASSWORD)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_user_gets_default_avatar(self):
        self.assertTrue(is_valid_avatar(self.user.avatar))

    def test_update_profile(self):
        avatar = AVATARS[3].id
        updated = self.store.update_profile(self.user.id, "  Desti   M ", "Halo!", avatar)
        self.assertEqual(updated.display_name, "Desti M")
        self.assertEqual(updated.bio, "Halo!")
        self.assertEqual(updated.avatar, avatar)

    def test_update_profile_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            self.store.update_profile(self.user.id, "Desti", "", "../../etc/passwd")
        with self.assertRaises(ValueError):
            self.store.update_profile(self.user.id, "Desti", "x" * 281, None)

    def test_email_change_requires_password_unique_email_and_confirmation(self):
        self.store.create_user("Other", "other@example.com", PASSWORD)
        with self.assertRaises(InvalidCurrentPasswordError):
            self.store.request_email_change(self.user.id, "wrong-password", "new@example.com")
        with self.assertRaises(DuplicateEmailError):
            self.store.request_email_change(self.user.id, PASSWORD, "OTHER@example.com")
        token = self.store.request_email_change(self.user.id, PASSWORD, "New@Example.com")
        # Not applied until the link from the new mailbox is opened.
        self.assertEqual(self.store.get_user(self.user.id).email, "desti@example.com")
        self.assertEqual(self.store.pending_email_change(self.user.id), "new@example.com")
        updated, previous = self.store.confirm_email_change(token)
        self.assertEqual((updated.email, previous), ("new@example.com", "desti@example.com"))
        self.assertTrue(updated.email_verified)
        self.assertIsNotNone(self.store.authenticate("new@example.com", PASSWORD))

    def test_change_password_rotates_epoch_and_hash(self):
        with self.assertRaises(InvalidCurrentPasswordError):
            self.store.change_password(self.user.id, "wrong-password", "AnotherPassword456")
        with self.assertRaises(ValueError):
            self.store.change_password(self.user.id, PASSWORD, "short")
        updated = self.store.change_password(self.user.id, PASSWORD, "AnotherPassword456")
        self.assertEqual(updated.session_epoch, self.user.session_epoch + 1)
        self.assertIsNone(self.store.authenticate("desti@example.com", PASSWORD))
        self.assertIsNotNone(self.store.authenticate("desti@example.com", "AnotherPassword456"))

    def test_legacy_database_is_migrated(self):
        legacy = Path(self.temp.name) / "legacy.db"
        with sqlite3.connect(legacy) as conn:
            conn.execute(
                """CREATE TABLE users (id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT)"""
            )
            conn.execute(
                "INSERT INTO users VALUES ('u1','Old','old@example.com','x','user',1,'t','t',NULL)"
            )
        user = UserStore(legacy).get_user("u1")
        self.assertIsNone(user.avatar)
        self.assertEqual(user.bio, "")
        self.assertTrue(user.avatar_url.startswith("/static/avatars/"))
        # Accounts that existed before verification was introduced are grandfathered.
        self.assertTrue(user.email_verified)


class AccountRouteTests(registration_tests.RegistrationRouteTests):
    """Reuses the registration route fixture (fake camera, temp DB)."""

    def register_and_login(self, email="desti@example.com"):
        self.client.get('/auth/register')
        self.client.post('/auth/register', data={
            'csrf_token': self.session_token('preauth_csrf_token'),
            'display_name': 'Desti', 'email': email,
            'password': PASSWORD, 'password_confirmation': PASSWORD,
            'avatar': AVATARS[0].id,
        })
        self.client.get('/auth/login')
        self.client.post('/auth/login', data={
            'csrf_token': self.session_token('preauth_csrf_token'),
            'auth_method': 'user', 'email': email, 'password': PASSWORD,
        })

    def test_account_page_shows_profile_and_chosen_avatar(self):
        self.register_and_login()
        response = self.client.get('/account')
        self.assertEqual(response.status_code, 200)
        self.assertIn(AVATARS[0].url.encode(), response.data)
        self.assertIn(b'Simpan profil', response.data)

    def test_profile_update_requires_csrf(self):
        self.register_and_login()
        response = self.client.post('/account/profile', data={'display_name': 'X Y', 'bio': ''})
        self.assertEqual(response.status_code, 403)

    def test_profile_update_flow(self):
        self.register_and_login()
        response = self.client.post('/account/profile', data={
            'csrf_token': self.session_token('csrf_token'),
            'display_name': 'Desti Baru', 'bio': 'Halo WeWatch', 'avatar': AVATARS[5].id,
        })
        self.assertEqual(response.status_code, 302)
        page = self.client.get('/account').data
        self.assertIn(b'Desti Baru', page)
        self.assertIn(b'Halo WeWatch', page)
        self.assertIn(b'Profil berhasil diperbarui', page)

        response = self.client.post('/account/profile', data={
            'csrf_token': self.session_token('csrf_token'),
            'display_name': 'Desti', 'bio': '', 'avatar': '../app.py',
        })
        self.assertEqual(response.status_code, 422)

    def test_email_change_requires_current_password(self):
        self.register_and_login()
        response = self.client.post('/account/email', data={
            'csrf_token': self.session_token('csrf_token'),
            'email': 'new@example.com', 'current_password': 'wrong',
        })
        self.assertEqual(response.status_code, 422)
        response = self.client.post('/account/email', data={
            'csrf_token': self.session_token('csrf_token'),
            'email': 'new@example.com', 'current_password': PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(b'new@example.com', self.client.get('/account').data)

    def test_password_change_revokes_other_sessions(self):
        self.register_and_login()
        other = self.module.app.test_client()
        with self.client.session_transaction() as s:
            copied = dict(s)
        with other.session_transaction() as s:
            s.update(copied)
        self.assertEqual(other.get('/account').status_code, 200)

        response = self.client.post('/account/password', data={
            'csrf_token': self.session_token('csrf_token'),
            'current_password': PASSWORD,
            'new_password': 'AnotherPassword456',
            'new_password_confirmation': 'AnotherPassword456',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/account').status_code, 200)
        self.assertEqual(other.get('/account').status_code, 302)

    def test_registered_user_still_cannot_reach_admin_dashboard(self):
        self.register_and_login()
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/status_data').status_code, 403)

    # Prevent inherited registration tests from running twice.
    test_register_login_account_and_logout = None
    test_invalid_csrf_and_weak_password_are_rejected = None
    test_admin_token_path_remains_available = None


if __name__ == "__main__":
    unittest.main()
