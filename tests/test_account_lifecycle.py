"""Email verification, password reset, uploads, export/delete, meeting tickets,
shared rate limiting, and PostgreSQL parity."""

import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from services import mailer
from services.avatars import AVATARS, upload_id
from services.room_auth import issue_room_token, verify_room_token
from services.user_store import InvalidTokenError, UserStore
from tests import test_auth_registration as registration_tests
from utils.security import RedisRateLimiter, SlidingWindowRateLimiter, make_rate_limiter

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import fakeredis
except ImportError:  # pragma: no cover
    fakeredis = None

PASSWORD = "StrongPassword123"
NEW_PASSWORD = "AnotherPassword456"
LINK_RE = re.compile(r"https?://\S+")


def last_link(to=None):
    mails = [mail for mail in mailer.outbox if to is None or mail.to == to]
    return LINK_RE.findall(mails[-1].body)[-1]


def image_bytes(fmt="PNG", size=(640, 480), exif=False):
    image = Image.new("RGB", size, (200, 30, 30))
    buffer = io.BytesIO()
    kwargs = {}
    if exif:
        exif_data = Image.Exif()
        exif_data[0x010F] = "SecretCameraMaker"  # Make
        kwargs["exif"] = exif_data
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


class StoreLifecycleTests(unittest.TestCase):
    """Runs on SQLite, and on PostgreSQL when WEBWATCH_TEST_DATABASE_URL is set."""

    database_url = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if self.database_url:
            self.store = UserStore(self.database_url)
            with self.store.db.transaction() as conn:
                conn.execute("DELETE FROM auth_tokens")
                conn.execute("DELETE FROM users")
        else:
            self.store = UserStore(Path(self.temp.name) / "users.db")
        self.user = self.store.create_user("Desti", "desti@example.com", PASSWORD)

    def tearDown(self):
        self.temp.cleanup()

    def test_email_verification_token_is_single_use(self):
        self.assertFalse(self.user.email_verified)
        token = self.store.issue_email_verification(self.user.id)
        self.assertTrue(self.store.verify_email(token).email_verified)
        with self.assertRaises(InvalidTokenError):
            self.store.verify_email(token)

    def test_new_token_invalidates_previous_one(self):
        first = self.store.issue_email_verification(self.user.id)
        second = self.store.issue_email_verification(self.user.id)
        with self.assertRaises(InvalidTokenError):
            self.store.verify_email(first)
        self.store.verify_email(second)

    def test_tokens_are_stored_hashed(self):
        token = self.store.issue_email_verification(self.user.id)
        with self.store.db.transaction() as conn:
            stored = [row["token_hash"] for row in conn.execute("SELECT token_hash FROM auth_tokens").fetchall()]
        self.assertNotIn(token, stored)

    def test_expired_token_is_rejected(self):
        token = self.store.issue_email_verification(self.user.id)
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE auth_tokens SET expires_at = ?", ("2000-01-01T00:00:00+00:00",))
        with self.assertRaises(InvalidTokenError):
            self.store.verify_email(token)

    def test_password_reset_flow(self):
        self.assertIsNone(self.store.request_password_reset("missing@example.com"))
        user, token = self.store.request_password_reset("DESTI@example.com")
        self.assertTrue(self.store.token_is_valid(token, "reset_password"))
        with self.assertRaises(ValueError):
            self.store.reset_password(token, "short")
        # A rejected weak password must not burn the token.
        updated = self.store.reset_password(token, NEW_PASSWORD)
        self.assertEqual(updated.session_epoch, user.session_epoch + 1)
        self.assertTrue(updated.email_verified)
        self.assertIsNotNone(self.store.authenticate("desti@example.com", NEW_PASSWORD))
        with self.assertRaises(InvalidTokenError):
            self.store.reset_password(token, "YetAnotherPassword789")

    def test_export_and_delete(self):
        exported = self.store.export_user(self.user.id)
        self.assertEqual(exported["email"], "desti@example.com")
        self.assertNotIn("password_hash", json.dumps(exported))
        self.store.issue_email_verification(self.user.id)
        self.store.delete_user(self.user.id, PASSWORD)
        self.assertIsNone(self.store.get_user(self.user.id))
        self.assertIsNone(self.store.authenticate("desti@example.com", PASSWORD))
        # Email can be reused after deletion.
        self.store.create_user("Desti", "desti@example.com", PASSWORD)

    def test_duplicate_email_case_insensitive(self):
        from services.user_store import DuplicateEmailError

        with self.assertRaises(DuplicateEmailError):
            self.store.create_user("Other", "DESTI@EXAMPLE.COM", PASSWORD)


@unittest.skipUnless(os.getenv("WEBWATCH_TEST_DATABASE_URL"), "PostgreSQL not configured")
class PostgresStoreLifecycleTests(StoreLifecycleTests):
    database_url = os.getenv("WEBWATCH_TEST_DATABASE_URL")


@unittest.skipIf(Image is None, "Pillow not installed")
class AvatarUploadProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("WEBWATCH_UPLOAD_DIR")
        os.environ["WEBWATCH_UPLOAD_DIR"] = self.temp.name

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("WEBWATCH_UPLOAD_DIR", None)
        else:
            os.environ["WEBWATCH_UPLOAD_DIR"] = self.previous
        self.temp.cleanup()

    def test_upload_is_reencoded_square_webp_without_exif(self):
        from services.avatar_uploads import process_avatar_upload

        out = process_avatar_upload(image_bytes("JPEG", exif=True))
        with Image.open(io.BytesIO(out)) as result:
            self.assertEqual(result.format, "WEBP")
            self.assertEqual(result.size, (256, 256))
            self.assertFalse(result.getexif())
        self.assertNotIn(b"SecretCameraMaker", out)

    def test_rejects_non_images_oversize_and_disallowed_formats(self):
        from services.avatar_uploads import AvatarUploadError, MAX_UPLOAD_BYTES, process_avatar_upload

        for payload in (b"", b"<svg onload=alert(1)>", b"GIF89a" + b"\0" * 100, b"x" * (MAX_UPLOAD_BYTES + 1)):
            with self.assertRaises(AvatarUploadError):
                process_avatar_upload(payload)
        with self.assertRaises(AvatarUploadError):
            process_avatar_upload(image_bytes("GIF"))

    def test_rejects_decompression_bombs(self):
        from services.avatar_uploads import AvatarUploadError, process_avatar_upload

        with self.assertRaises(AvatarUploadError):
            process_avatar_upload(image_bytes("PNG", size=(5000, 5000)))


class RateLimiterTests(unittest.TestCase):
    def test_without_redis_url_uses_memory(self):
        self.assertIsInstance(make_rate_limiter("x", 1, 1, None), SlidingWindowRateLimiter)

    @unittest.skipIf(fakeredis is None, "fakeredis not installed")
    def test_redis_limiter_is_shared_between_instances(self):
        client = fakeredis.FakeRedis()
        replica_a = RedisRateLimiter(client, "login", 2, 60)
        replica_b = RedisRateLimiter(client, "login", 2, 60)
        self.assertTrue(replica_a.allow("1.2.3.4"))
        self.assertTrue(replica_b.allow("1.2.3.4"))
        self.assertFalse(replica_a.allow("1.2.3.4"))
        self.assertTrue(replica_b.allow("5.6.7.8"))

    def test_redis_outage_falls_back_to_local_limit(self):
        class BrokenRedis:
            def pipeline(self):
                raise ConnectionError("down")

        limiter = RedisRateLimiter(BrokenRedis(), "login", 1, 60)
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))


class MeetingTicketTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get("WEBRTC_SECRET_KEY")
        os.environ["WEBRTC_SECRET_KEY"] = "s" * 64

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("WEBRTC_SECRET_KEY", None)
        else:
            os.environ["WEBRTC_SECRET_KEY"] = self.previous

    def test_profile_claims_are_signed_and_sanitized(self):
        token = issue_room_token(
            "room", "user:1", "client", 300,
            profile={"name": "  Desti   M ", "avatar": "javascript:alert(1)"},
        )
        claims = verify_room_token(token, "room")
        self.assertEqual(claims["profile"], {"name": "Desti M"})
        token = issue_room_token("room", "user:1", "client", 300, profile={"avatar": "https://x.test/a.svg"})
        self.assertEqual(verify_room_token(token, "room")["profile"]["avatar"], "https://x.test/a.svg")


class AccountLifecycleRouteTests(registration_tests.RegistrationRouteTests):
    def setUp(self):
        self.extra_env = {key: os.environ.get(key) for key in (
            "WEBWATCH_MAIL_BACKEND", "WEBWATCH_UPLOAD_DIR", "WEBRTC_SECRET_KEY", "WEBWATCH_PUBLIC_URL",
        )}
        self.upload_temp = tempfile.TemporaryDirectory()
        os.environ["WEBWATCH_MAIL_BACKEND"] = "memory"
        os.environ["WEBWATCH_UPLOAD_DIR"] = self.upload_temp.name
        os.environ["WEBRTC_SECRET_KEY"] = "s" * 64
        os.environ["WEBWATCH_PUBLIC_URL"] = "https://watch.example"
        mailer.outbox.clear()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        for key, value in self.extra_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.upload_temp.cleanup()
        mailer.outbox.clear()

    def register(self, email="desti@example.com"):
        self.client.get('/auth/register')
        return self.client.post('/auth/register', data={
            'csrf_token': self.session_token('preauth_csrf_token'),
            'display_name': 'Desti', 'email': email,
            'password': PASSWORD, 'password_confirmation': PASSWORD,
        })

    def login(self, email="desti@example.com", password=PASSWORD):
        self.client.get('/auth/login')
        return self.client.post('/auth/login', data={
            'csrf_token': self.session_token('preauth_csrf_token'),
            'auth_method': 'user', 'email': email, 'password': password,
        })

    def path_of(self, link):
        self.assertTrue(link.startswith("https://watch.example/"), link)
        return urlparse(link).path

    def test_registration_sends_verification_and_link_verifies(self):
        self.register()
        self.assertEqual(mailer.outbox[-1].to, "desti@example.com")
        self.login()
        self.assertIn(b'Email belum diverifikasi', self.client.get('/account').data)
        response = self.client.get(self.path_of(last_link()))
        self.assertEqual(response.status_code, 302)
        page = self.client.get('/account').data
        self.assertIn(b'Terverifikasi', page)
        self.assertNotIn(b'Email belum diverifikasi', page)
        self.assertEqual(self.client.get(self.path_of(last_link())).status_code, 400)

    def test_login_blocked_until_verified_when_required(self):
        self.register()
        self.module.REQUIRE_EMAIL_VERIFICATION = True
        response = self.login()
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Email belum diverifikasi', response.data)
        self.client.get(self.path_of(last_link()))
        self.assertEqual(self.login().status_code, 302)

    def test_forgot_and_reset_password(self):
        self.register()
        self.client.get('/auth/forgot-password')
        csrf = self.session_token('preauth_csrf_token')
        before = len(mailer.outbox)
        response = self.client.post('/auth/forgot-password', data={'csrf_token': csrf, 'email': 'nobody@example.com'})
        self.assertIn(b'Jika email tersebut terdaftar', response.data)
        self.assertEqual(len(mailer.outbox), before)  # no mail, same response
        response = self.client.post('/auth/forgot-password', data={'csrf_token': csrf, 'email': 'desti@example.com'})
        self.assertIn(b'Jika email tersebut terdaftar', response.data)
        reset_path = self.path_of(last_link("desti@example.com"))

        self.assertEqual(self.client.get(reset_path).status_code, 200)
        response = self.client.post(reset_path, data={
            'csrf_token': self.session_token('preauth_csrf_token'),
            'password': NEW_PASSWORD, 'password_confirmation': NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.login(password=PASSWORD).status_code, 200)  # generic error page
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 302)
        self.assertEqual(self.client.get(reset_path).status_code, 400)
        self.assertEqual(self.client.get('/auth/reset-password/garbage').status_code, 400)

    def test_email_change_needs_confirmation_link_and_notifies_old_address(self):
        self.register()
        self.login()
        response = self.client.post('/account/email', data={
            'csrf_token': self.session_token('csrf_token'),
            'email': 'new@example.com', 'current_password': PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(b'Menunggu konfirmasi', self.client.get('/account').data)
        confirm = self.path_of(last_link("new@example.com"))
        self.assertEqual(self.client.get(confirm).status_code, 302)
        self.assertEqual(mailer.outbox[-1].to, "desti@example.com")  # notice to old address
        self.assertEqual(self.login("new@example.com").status_code, 302)

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_photo_upload_serve_and_remove(self):
        self.register()
        self.login()
        response = self.client.post('/account/avatar/upload', data={
            'csrf_token': self.session_token('csrf_token'),
            'photo': (io.BytesIO(image_bytes("JPEG", exif=True)), 'me.jpg'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        user = self.module.user_store.get_user(self.session_token('user_id'))
        self.assertTrue(upload_id(user.avatar))
        served = self.client.get(user.avatar_url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, 'image/webp')
        self.assertIn("default-src 'none'", served.headers['Content-Security-Policy'])
        stored = Path(self.upload_temp.name) / 'avatars' / f'{upload_id(user.avatar)}.webp'
        self.assertTrue(stored.exists())

        bad = self.client.post('/account/avatar/upload', data={
            'csrf_token': self.session_token('csrf_token'),
            'photo': (io.BytesIO(b'<svg onload=alert(1)>'), 'x.svg'),
        }, content_type='multipart/form-data')
        self.assertEqual(bad.status_code, 422)

        self.client.post('/account/avatar/remove', data={'csrf_token': self.session_token('csrf_token')})
        self.assertFalse(stored.exists())
        self.assertEqual(self.client.get('/media/avatars/../../app.py').status_code, 404)

    def test_export_requires_post_and_contains_profile(self):
        self.register()
        self.login()
        self.assertIn(self.client.get('/account/export').status_code, (403, 405))
        response = self.client.post('/account/export', data={'csrf_token': self.session_token('csrf_token')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        data = json.loads(response.data)
        self.assertEqual(data['account']['email'], 'desti@example.com')
        self.assertNotIn('password', response.data.decode().lower().replace('password_', ''))

    def test_delete_account_requires_password_and_confirmation(self):
        self.register()
        self.login()
        csrf = self.session_token('csrf_token')
        r = self.client.post('/account/delete', data={'csrf_token': csrf, 'current_password': PASSWORD, 'confirm': 'no'})
        self.assertEqual(r.status_code, 422)
        r = self.client.post('/account/delete', data={'csrf_token': csrf, 'current_password': 'wrong', 'confirm': 'HAPUS'})
        self.assertEqual(r.status_code, 422)
        r = self.client.post('/account/delete', data={'csrf_token': csrf, 'current_password': PASSWORD, 'confirm': 'HAPUS'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get('/account').status_code, 302)
        self.assertEqual(self.login().status_code, 200)  # account gone

    def test_meeting_redirect_carries_signed_profile(self):
        # The shared fixture stubs room_auth; use the real signer here.
        self.module.issue_room_token = issue_room_token
        self.register()
        self.login()
        response = self.client.get('/account/meeting')
        self.assertEqual(response.status_code, 302)
        ticket = parse_qs(urlparse(response.location).query)['join_token'][0]
        claims = verify_room_token(ticket, self.module.WEBRTC_ROOM_NAME)
        self.assertEqual(claims['role'], 'client')
        self.assertTrue(claims['identity'].startswith('user:'))
        self.assertEqual(claims['profile']['name'], 'Desti')
        self.assertTrue(claims['profile']['avatar'].startswith('https://watch.example/static/avatars/'))

    test_register_login_account_and_logout = None
    test_invalid_csrf_and_weak_password_are_rejected = None
    test_admin_token_path_remains_available = None


if __name__ == "__main__":
    unittest.main()
