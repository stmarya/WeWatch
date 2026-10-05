import sqlite3
import tempfile
from pathlib import Path
import unittest

from services.user_store import DuplicateEmailError, UserStore, normalize_email, validate_registration


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "users.db"
        self.store = UserStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_registration_persists_normalized_user_and_hashes_password(self):
        user = self.store.create_user("  Desti   Marliyana ", "DESTI@Example.COM", "StrongPassword123")
        self.assertEqual(user.display_name, "Desti Marliyana")
        self.assertEqual(user.email, "desti@example.com")
        self.assertEqual(user.role, "user")
        with sqlite3.connect(self.db_path) as conn:
            stored_hash = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()[0]
        self.assertNotEqual(stored_hash, "StrongPassword123")
        self.assertTrue(stored_hash.startswith("scrypt$"))

    def test_authentication_updates_last_login(self):
        created = self.store.create_user("Desti", "desti@example.com", "StrongPassword123")
        authenticated = self.store.authenticate("DESTI@example.com", "StrongPassword123")
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated.id, created.id)
        self.assertIsNotNone(authenticated.last_login_at)
        self.assertIsNone(self.store.authenticate("desti@example.com", "wrong-password"))

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.store.create_user("Desti", "desti@example.com", "StrongPassword123")
        with self.assertRaises(DuplicateEmailError):
            self.store.create_user("Other", "DESTI@EXAMPLE.COM", "AnotherPassword123")

    def test_validation_rejects_invalid_fields(self):
        errors = validate_registration("A", "not-an-email", "short")
        self.assertEqual({"display_name", "email", "password"}, set(errors))
        self.assertEqual("desti@example.com", normalize_email(" DESTI@Example.COM "))


if __name__ == "__main__":
    unittest.main()
