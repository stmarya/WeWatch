"""Phase 1 contracts: real DB/password/session paths, no camera/cloud dependencies."""
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from platform_app import create_app
from platform_core.mail import MailDeliveryError, Mailer
from platform_core.security import PlatformError, email_address
from platform_core.store import Store

PASSWORD = 'test-only-passphrase-2026'


class TestMailbox:
    ready = True
    def __init__(self):
        self.messages = []
    def send(self, recipient, subject, body):
        self.messages.append({'recipient': recipient, 'subject': subject, 'body': body})
    def token(self, recipient=None):
        message = next(m for m in reversed(self.messages) if recipient is None or m['recipient'] == recipient)
        return re.search(r'#token=([A-Za-z0-9_-]+)', message['body'])[1]


class PlatformFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.mailbox = TestMailbox()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-platform-secret-' * 3,
            'DATABASE': str(Path(self.directory.name) / 'platform.sqlite3'),
            'TEST_MAILER': self.mailbox, 'RATE_LIMITS_ENABLED': False,
            'PUBLIC_URL': 'http://localhost', 'ENVIRONMENT': 'development'})
        self.client = self.app.test_client()
        self.store = self.app.extensions['platform_store']
        self.connection = self.store.connect()

    def tearDown(self):
        self.connection.close(); self.directory.cleanup()

    def post(self, path, data=None, client=None):
        client = client or self.client
        csrf = client.get('/api/session').json['csrf_token']
        return client.post(path, json=data or {}, headers={'X-CSRF-Token': csrf})

    def account(self, email='owner@example.com', client=None, verify=True, login=True):
        client = client or self.client
        response = self.post('/register', {'email': email, 'password': PASSWORD, 'display_name': 'Test Person'}, client)
        self.assertEqual(response.status_code, 200)
        if verify:
            self.assertEqual(self.post('/verify-email', {'token': self.mailbox.token(email)}, client).status_code, 200)
        if login:
            self.assertEqual(self.post('/login', {'email': email, 'password': PASSWORD}, client).status_code, 200)
        return self.connection.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()['id']

    def workspace(self, name='Workspace A', client=None):
        response = self.post('/workspaces', {'name': name}, client)
        self.assertEqual(response.status_code, 200)
        return response.json['workspace_id']

    def invite(self, workspace_id, email, role='member', client=None):
        response = self.post(f'/workspaces/{workspace_id}/invitations', {'email': email, 'role': role}, client)
        self.assertEqual(response.status_code, 200)
        return self.mailbox.token(email)

    def member(self, workspace_id, email='member@example.com', role='member'):
        client = self.app.test_client()
        user_id = self.account(email, client)
        token = self.invite(workspace_id, email, role)
        self.assertEqual(self.post('/invitations/accept', {'token': token}, client).status_code, 200)
        return client, user_id


class PlatformTests(PlatformFixture):
    def test_register_hashes_password_and_does_not_leak_tokens(self):
        response = self.post('/register', {'email': 'OWNER@example.com', 'password': PASSWORD, 'display_name': 'Owner', 'role': 'owner'})
        self.assertEqual(response.status_code, 200)
        row = self.connection.execute('SELECT * FROM users').fetchone()
        self.assertEqual(row['email'], 'owner@example.com')
        self.assertTrue(row['password_hash'].startswith('scrypt:'))
        self.assertNotIn(PASSWORD, row['password_hash'])
        raw = self.mailbox.token()
        self.assertNotIn(raw, response.text)
        stored = self.connection.execute('SELECT token_hash FROM account_tokens').fetchone()[0]
        self.assertNotEqual(raw, stored)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM memberships').fetchone()[0], 0)

    def test_duplicate_register_has_same_response(self):
        self.account(login=False)
        response = self.post('/register', {'email': 'owner@example.com', 'password': PASSWORD})
        another = self.post('/register', {'email': 'other@example.com', 'password': PASSWORD})
        self.assertEqual(response.json, another.json)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM users WHERE email='owner@example.com'").fetchone()[0], 1)

    def test_unverified_account_cannot_login_or_create_workspace(self):
        self.account(verify=False, login=False)
        self.assertEqual(self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(self.post('/workspaces', {'name': 'No'}).status_code, 401)

    def test_verify_one_time_expiry_and_purpose(self):
        self.account(verify=False, login=False)
        raw = self.mailbox.token()
        self.assertEqual(self.post('/password/reset', {'token': raw, 'password': PASSWORD}).status_code, 400)
        self.assertEqual(self.post('/verify-email', {'token': raw}).status_code, 200)
        self.assertEqual(self.post('/verify-email', {'token': raw}).status_code, 400)
        self.account('expired@example.com', verify=False, login=False)
        raw = self.mailbox.token('expired@example.com')
        self.connection.execute('UPDATE account_tokens SET expires_at=0')
        self.assertEqual(self.post('/verify-email', {'token': raw}).status_code, 400)

    def test_resend_revokes_previous_verification_token(self):
        self.account(verify=False, login=False)
        old = self.mailbox.token()
        self.assertEqual(self.post('/verification/resend', {'email': 'owner@example.com'}).status_code, 200)
        self.assertEqual(self.post('/verify-email', {'token': old}).status_code, 400)
        self.assertEqual(self.post('/verify-email', {'token': self.mailbox.token()}).status_code, 200)

    def test_login_rotates_csrf_and_issues_separate_cookie(self):
        self.account(login=False)
        old = self.client.get('/api/session').json['csrf_token']
        response = self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD})
        self.assertIn('wewatch_platform=', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
        self.assertEqual(self.client.post('/workspaces', json={'name': 'No'}, headers={'X-CSRF-Token': old}).status_code, 403)
        self.assertNotEqual(old, self.client.get('/api/session').json['csrf_token'])

    def test_no_role_or_hash_in_public_me(self):
        self.account()
        response = self.client.get('/api/me')
        self.assertEqual(response.status_code, 200)
        for field in ('password_hash', 'token_hash', 'session_id', 'account_session'):
            self.assertNotIn(field, response.text)

    def test_all_mutations_require_csrf_including_login(self):
        self.client.get('/login')
        for path in ('/login', '/register', '/password/forgot', '/verify-email', '/workspaces', '/logout'):
            self.assertEqual(self.client.post(path, json={}).status_code, 403)

    def test_form_post_under_no_referrer_policy_still_requires_csrf(self):
        csrf = self.client.get('/api/session').json['csrf_token']
        form = {'email':'form@example.com', 'password':PASSWORD, 'csrf_token':csrf}
        self.assertEqual(self.client.post('/register', data=form, headers={'Origin':'null','Sec-Fetch-Site':'same-origin'}).status_code, 302)
        self.assertEqual(self.client.post('/register', data=form, headers={'Origin':'null','Sec-Fetch-Site':'cross-site'}).status_code, 403)
        self.assertEqual(self.client.post('/register', data={'email':'x@example.com','password':PASSWORD}, headers={'Origin':'null','Sec-Fetch-Site':'same-origin'}).status_code, 403)

    def test_external_origin_rejected_even_with_csrf(self):
        token = self.client.get('/api/session').json['csrf_token']
        response = self.client.post('/login', json={}, headers={'X-CSRF-Token': token, 'Origin': 'https://attacker.example'})
        self.assertEqual(response.status_code, 403)

    def test_logout_revokes_server_session(self):
        self.account()
        stored = self.connection.execute('SELECT id FROM account_sessions').fetchone()[0]
        self.assertEqual(self.post('/logout').status_code, 200)
        self.assertIsNotNone(self.connection.execute('SELECT revoked_at FROM account_sessions WHERE id=?', (stored,)).fetchone()[0])
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_logout_all_revokes_other_browser(self):
        self.account()
        second = self.app.test_client()
        self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD}, second)
        self.assertEqual(self.post('/account/logout-all').status_code, 200)
        self.assertEqual(second.get('/api/me').status_code, 401)

    def test_reset_is_one_use_and_revokes_existing_sessions(self):
        self.account()
        second = self.app.test_client()
        self.assertEqual(self.post('/password/forgot', {'email': 'owner@example.com'}, second).status_code, 200)
        token = self.mailbox.token()
        password = 'new-test-only-passphrase-2026'
        self.assertEqual(self.post('/password/reset', {'token': token, 'password': password}, second).status_code, 200)
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.post('/password/reset', {'token': token, 'password': password}, second).status_code, 400)
        self.assertEqual(self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD}, second).status_code, 401)
        self.assertEqual(self.post('/login', {'email': 'owner@example.com', 'password': password}, second).status_code, 200)

    def test_forgot_password_does_not_enumerate_accounts(self):
        self.account(login=False)
        existing = self.post('/password/forgot', {'email': 'owner@example.com'})
        unknown = self.post('/password/forgot', {'email': 'missing@example.com'})
        self.assertEqual(existing.json, unknown.json)

    def test_disabled_account_and_expired_sessions_denied(self):
        user_id = self.account()
        self.connection.execute('UPDATE users SET disabled_at=? WHERE id=?', (int(time.time()), user_id))
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD}).status_code, 401)
        self.connection.execute('UPDATE users SET disabled_at=NULL WHERE id=?', (user_id,))
        self.post('/login', {'email': 'owner@example.com', 'password': PASSWORD})
        self.connection.execute('UPDATE account_sessions SET expires_at=0')
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_idle_timeout_denies_session(self):
        self.account()
        self.connection.execute('UPDATE account_sessions SET last_seen_at=0')
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_workspace_creator_is_owner_atomically(self):
        user_id = self.account(); workspace_id = self.workspace()
        membership = self.connection.execute('SELECT * FROM memberships WHERE workspace_id=?', (workspace_id,)).fetchone()
        self.assertEqual((membership['user_id'], membership['role']), (user_id, 'owner'))
        self.assertEqual(self.client.get(f'/api/workspaces/{workspace_id}').json['workspace']['role'], 'owner')

    def test_tenant_isolation_across_read_write_and_audit(self):
        self.account(); workspace_id = self.workspace()
        outsider = self.app.test_client(); self.account('outside@example.com', outsider)
        self.assertEqual(outsider.get(f'/api/workspaces/{workspace_id}').status_code, 404)
        self.assertEqual(outsider.get(f'/api/workspaces/{workspace_id}/audit').status_code, 404)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/settings', {'name': 'Hacked'}, outsider).status_code, 404)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/invitations', {'email': 'x@example.com'}, outsider).status_code, 404)
        self.assertEqual(outsider.get('/api/me').json['workspaces'], [])

    def test_invitation_acceptance_is_email_bound(self):
        self.account(); workspace_id = self.workspace()
        invited = self.app.test_client(); self.account('invited@example.com', invited)
        outsider = self.app.test_client(); self.account('other@example.com', outsider)
        token = self.invite(workspace_id, 'invited@example.com', 'viewer')
        self.assertEqual(self.post('/invitations/accept', {'token': token}, outsider).status_code, 400)
        self.assertEqual(self.post('/invitations/accept', {'token': token, 'role': 'owner'}, invited).status_code, 200)
        self.assertEqual(invited.get(f'/api/workspaces/{workspace_id}').json['workspace']['role'], 'viewer')
        self.assertEqual(self.post('/invitations/accept', {'token': token}, invited).status_code, 400)

    def test_invitation_cannot_be_reused_when_revoked_or_expired(self):
        self.account(); workspace_id = self.workspace()
        invited = self.app.test_client(); self.account('invited@example.com', invited)
        token = self.invite(workspace_id, 'invited@example.com')
        invitation_id = self.connection.execute('SELECT id FROM invitations').fetchone()[0]
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/invitations/{invitation_id}/revoke').status_code, 200)
        self.assertEqual(self.post('/invitations/accept', {'token': token}, invited).status_code, 400)
        token = self.invite(workspace_id, 'invited@example.com')
        self.connection.execute('UPDATE invitations SET expires_at=0')
        self.assertEqual(self.post('/invitations/accept', {'token': token}, invited).status_code, 400)

    def test_viewer_cannot_mutate_or_read_audit(self):
        self.account(); workspace_id = self.workspace()
        viewer, viewer_id = self.member(workspace_id, role='viewer')
        self.assertEqual(viewer.get(f'/api/workspaces/{workspace_id}/audit').status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/settings', {'name': 'No'}, viewer).status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/invitations', {'email': 'new@example.com'}, viewer).status_code, 403)
        page = viewer.get(f'/workspaces/{workspace_id}')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('owner@example.com', page.text)

    def test_admin_cannot_promote_itself_or_manage_owner(self):
        owner_id = self.account(); workspace_id = self.workspace()
        admin, admin_id = self.member(workspace_id, 'admin@example.com', 'admin')
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{admin_id}/role', {'role': 'owner'}, admin).status_code, 400)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{owner_id}/remove', client=admin).status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/invitations', {'email': 'x@example.com', 'role': 'admin'}, admin).status_code, 403)

    def test_admin_can_manage_member_but_not_another_admin(self):
        self.account(); workspace_id = self.workspace()
        admin, admin_id = self.member(workspace_id, 'admin@example.com', 'admin')
        viewer, viewer_id = self.member(workspace_id, 'viewer@example.com', 'viewer')
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{viewer_id}/role', {'role': 'host'}, admin).status_code, 200)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{viewer_id}/remove', client=admin).status_code, 200)
        self.assertEqual(viewer.get(f'/api/workspaces/{workspace_id}').status_code, 404)

    def test_owner_cannot_leave_or_remove_itself_without_transfer(self):
        owner_id = self.account(); workspace_id = self.workspace()
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/leave').status_code, 409)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{owner_id}/remove').status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{owner_id}/role', {'role': 'viewer'}).status_code, 403)

    def test_transfer_requires_password_and_current_membership(self):
        owner_id = self.account(); workspace_id = self.workspace()
        member, member_id = self.member(workspace_id)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/ownership', {'member_id': member_id, 'password': 'wrong'}).status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/ownership', {'member_id': 'outside', 'password': PASSWORD}).status_code, 400)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/ownership', {'member_id': member_id, 'password': PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/workspaces/{workspace_id}').json['workspace']['role'], 'admin')
        self.assertEqual(member.get(f'/api/workspaces/{workspace_id}').json['workspace']['role'], 'owner')
        self.assertEqual(self.connection.execute("SELECT count(*) FROM memberships WHERE workspace_id=? AND role='owner'", (workspace_id,)).fetchone()[0], 1)

    def test_invitation_rechecks_inviter_role_at_acceptance(self):
        self.account(); workspace_id = self.workspace()
        admin, admin_id = self.member(workspace_id, 'admin@example.com', 'admin')
        invited = self.app.test_client(); self.account('invited@example.com', invited)
        token = self.invite(workspace_id, 'invited@example.com', 'member', admin)
        self.post(f'/workspaces/{workspace_id}/members/{admin_id}/role', {'role': 'viewer'})
        self.assertEqual(self.post('/invitations/accept', {'token': token}, invited).status_code, 400)

    def test_audit_events_do_not_include_password_or_raw_tokens(self):
        self.account(); workspace_id = self.workspace()
        raw = self.invite(workspace_id, 'invited@example.com')
        text = self.client.get(f'/api/workspaces/{workspace_id}/audit').text
        self.assertNotIn(raw, text); self.assertNotIn(PASSWORD, text)
        self.assertIn('member.invited', text)
        self.assertNotIn('invited@example.com', text)

    def test_rate_limit_login(self):
        self.app.config['RATE_LIMITS_ENABLED'] = True
        responses = [self.post('/login', {'email': 'missing@example.com', 'password': PASSWORD}).status_code for _ in range(16)]
        self.assertEqual(responses[-1], 429)

    def test_mail_disabled_fails_closed_without_exposing_token(self):
        self.app.extensions['platform_mailer'] = type('Disabled', (), {'ready': False})()
        response = self.post('/register', {'email': 'x@example.com', 'password': PASSWORD})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_invalid_json_password_and_name_validation(self):
        csrf = self.client.get('/api/session').json['csrf_token']
        self.assertEqual(self.client.post('/register', json=[], headers={'X-CSRF-Token': csrf}).status_code, 400)
        for value in ('short', ['invalid'], 'x'*129):
            self.assertEqual(self.post('/register', {'email': 'x@example.com', 'password': value}).status_code, 400)
        self.account(); workspace_id = self.workspace()
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/anything/role', {'role': []}).status_code, 400)
        self.assertEqual(self.post('/workspaces', {'name': 'x'*81}).status_code, 400)

    def test_security_headers_and_host_validation(self):
        response = self.client.get('/login')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        self.assertIn('camera=()', response.headers['Permissions-Policy'])
        self.assertEqual(self.client.get('/login', headers={'Host': 'attacker.example'}).status_code, 400)

    def test_platform_does_not_unlock_legacy_hardware_endpoints(self):
        self.account()
        for route in ('/video_feed','/status_data','/gallery'):
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.post('/toggle', {'feature': 'keamanan', 'state': True}).status_code, 404)

    def test_schema_migration_is_idempotent_and_foreign_keys_active(self):
        self.account(); self.store.migrate()
        self.assertEqual(self.connection.execute('SELECT count(*) FROM users').fetchone()[0], 1)
        self.assertEqual(self.connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute('INSERT INTO memberships VALUES (?,?,?,?)', ('missing', 'missing', 'owner', 0))

    def test_templates_escape_workspace_and_display_names(self):
        self.account(); self.workspace('<img src=x onerror=alert(1)>')
        response = self.client.get('/app')
        self.assertIn('&lt;img', response.text)
        self.assertNotIn('<img src=x', response.text)


class PlatformConfigurationTests(unittest.TestCase):
    def test_short_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            create_app({'SECRET_KEY': ''})

    def test_production_http_or_file_mail_is_rejected(self):
        for config in ({'PUBLIC_URL': 'http://localhost'}, {'PUBLIC_URL': 'https://app.example.com', 'MAIL_TRANSPORT': 'file'}):
            with self.assertRaises(ValueError):
                create_app({'SECRET_KEY': 'test-only-'*5, 'ENVIRONMENT': 'production', **config})

    def test_file_mail_requires_private_loopback_development(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'MAIL_TRANSPORT':'file','ENVIRONMENT':'development','PUBLIC_URL':'http://localhost',
                      'MAIL_DIRECTORY':folder,'MAIL_FROM':'no-reply@example.com'}
            mailer = Mailer(config)
            mailer.send('recipient@example.com', 'Test fixture', 'No real user data')
            files = list(Path(folder).glob('*.eml'))
            self.assertEqual(len(files), 1)
            if os.name != 'nt':
                self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                Mailer({**config, 'PUBLIC_URL':'https://app.example.com'})

    def test_email_validation_rejects_header_injection(self):
        for value in ('x@example.com\nBcc: x@evil.com', ['x'], 'x@@example.com'):
            with self.assertRaises(PlatformError):
                email_address(value)


class ExtraBoundaryTests(PlatformFixture):
    def test_stolen_cookie_cannot_replay_after_logout(self):
        self.account()
        replay = self.app.test_client()
        replay.set_cookie('wewatch_platform', self.client.get_cookie('wewatch_platform').value)
        self.assertEqual(replay.get('/api/me').status_code, 200)
        self.post('/logout')
        self.assertEqual(replay.get('/api/me').status_code, 401)

    def test_second_admin_cannot_be_demoted_by_admin(self):
        self.account(); workspace_id = self.workspace()
        admin, _ = self.member(workspace_id, 'admin@example.com', 'admin')
        other_admin, other_id = self.member(workspace_id, 'second-admin@example.com', 'admin')
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{other_id}/role', {'role':'viewer'}, admin).status_code, 403)
        self.assertEqual(self.post(f'/workspaces/{workspace_id}/members/{other_id}/remove', client=admin).status_code, 403)
        self.assertEqual(other_admin.get(f'/api/workspaces/{workspace_id}').json['workspace']['role'], 'admin')

    def test_owner_transfer_is_atomic_under_competing_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from platform_core.workspaces import transfer_ownership
        owner_id = self.account(); workspace_id = self.workspace()
        _, first = self.member(workspace_id, 'first@example.com')
        _, second = self.member(workspace_id, 'second@example.com')
        def transfer(target):
            connection = self.store.connect()
            try:
                transfer_ownership(connection, workspace_id, owner_id, target, PASSWORD)
                return True
            except PlatformError:
                return False
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(transfer, [first, second]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM memberships WHERE workspace_id=? AND role='owner'", (workspace_id,)).fetchone()[0], 1)

    def test_token_consumption_is_atomic_under_replay_race(self):
        from concurrent.futures import ThreadPoolExecutor
        from platform_core.accounts import consume_account_token
        self.account(verify=False, login=False)
        raw = self.mailbox.token()
        def consume(_):
            connection = self.store.connect()
            try:
                consume_account_token(connection, raw, 'verify')
                return True
            except PlatformError:
                return False
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        self.assertEqual(sum(results), 1)



if __name__ == '__main__':
    unittest.main()
