"""Phase 2 server contracts; browser reports are not trusted identity/permission attestations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch
from test_platform import PlatformFixture, PASSWORD
from platform_core import devices
from platform_core.security import PlatformError
from platform_core.store import Store, SCHEMA


class OnboardingTests(PlatformFixture):
    def setUp(self):
        super().setUp()
        self.owner = self.account()
        self.ws = self.workspace()

    def begin(self, client=None, workspace=None, name='Browser laptop'):
        response = self.post(f'/workspaces/{workspace or self.ws}/pairing', {'name':name}, client)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json['pairing']

    def approve(self, token, client=None):
        return self.post('/device-pairing/approve', {'token':token,'acknowledged':True}, client)

    def pair(self, client=None, workspace=None):
        pairing = self.begin(client, workspace)
        response = self.approve(pairing['token'], client)
        self.assertEqual(response.status_code, 200, response.text)
        status = (client or self.client).get(f'/api/workspaces/{workspace or self.ws}/onboarding').json
        return status['device']['id']

    def grant(self, device, capability='camera_preview', client=None, **extra):
        value = {'capability':capability,'policy_version':devices.POLICY_VERSION,'acknowledged':True}
        value.update(extra)
        return self.post(f'/workspaces/{self.ws}/devices/{device}/consents', value, client)

    def session_id(self, client=None):
        with (client or self.client).session_transaction() as state:
            from platform_core.security import token_hash
            digest = token_hash(state['account_session'])
        return self.connection.execute('SELECT id FROM account_sessions WHERE token_hash=?',(digest,)).fetchone()[0]

    def test_no_media_permission_on_default_pages_only_onboarding(self):
        self.assertIn('camera=()',self.client.get('/app').headers['Permissions-Policy'])
        page=self.client.get(f'/workspaces/{self.ws}/onboarding')
        self.assertIn('camera=(self)',page.headers['Permissions-Policy'])
        self.assertNotIn('unsafe-inline',page.headers['Content-Security-Policy'])
        self.assertIn('media-src',page.headers['Content-Security-Policy'])
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents').fetchone()[0],0)

    def test_pairing_is_hashed_scoped_and_one_use(self):
        pairing=self.begin()
        row=self.connection.execute('SELECT * FROM device_pairings').fetchone()
        self.assertNotEqual(row['token_hash'],pairing['token'])
        self.assertEqual(row['workspace_id'],self.ws)
        self.assertLessEqual(pairing['expires_at']-int(time.time()),300)
        self.assertEqual(self.client.get('/device-pairing').status_code,200)
        self.assertIsNone(self.connection.execute('SELECT used_at FROM device_pairings').fetchone()[0])
        self.assertEqual(self.approve(pairing['token']).status_code,200)
        self.assertEqual(self.approve(pairing['token']).status_code,404)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM browser_devices').fetchone()[0],1)
        self.assertEqual(self.client.get(f'/api/workspaces/{self.ws}/onboarding').json['grants'],[])

    def test_pairing_requires_explicit_acknowledgment(self):
        token=self.begin()['token']
        for ack in (False,'true',None,1):
            self.assertEqual(self.post('/device-pairing/approve',{'token':token,'acknowledged':ack}).status_code,400)
        self.assertEqual(self.approve(token).status_code,200)

    def test_same_account_approval_binds_requesting_session_not_approver(self):
        request_session=self.session_id(); token=self.begin()['token']
        other=self.app.test_client(); self.post('/login',{'email':'owner@example.com','password':PASSWORD},other)
        self.assertEqual(self.approve(token,other).status_code,200)
        self.assertEqual(self.connection.execute('SELECT session_id FROM browser_devices').fetchone()[0],request_session)
        self.assertIsNone(other.get(f'/api/workspaces/{self.ws}/onboarding').json['device'])

    def test_another_account_in_workspace_cannot_inspect_or_approve(self):
        member,_=self.member(self.ws)
        token=self.begin()['token']
        self.assertEqual(self.post('/device-pairing/inspect',{'token':token},member).status_code,404)
        self.assertEqual(self.approve(token,member).status_code,404)
        self.assertEqual(self.approve(token).status_code,200)

    def test_viewer_cannot_pair(self):
        viewer,_=self.member(self.ws,role='viewer')
        self.assertEqual(self.post(f'/workspaces/{self.ws}/pairing',{'name':'No'},viewer).status_code,403)
        page=viewer.get(f'/workspaces/{self.ws}/onboarding')
        self.assertEqual(page.status_code,200)
        self.assertNotIn('id="pair-form"',page.text)
        self.assertIn('camera=()',page.headers['Permissions-Policy'])

    def test_foreign_workspace_and_device_are_404(self):
        outsider=self.app.test_client(); self.account('outsider@example.com',outsider)
        device=self.pair()
        self.assertEqual(outsider.get(f'/workspaces/{self.ws}/onboarding').status_code,404)
        self.assertEqual(outsider.get(f'/api/workspaces/{self.ws}/onboarding').status_code,404)
        self.assertEqual(self.post(f'/workspaces/{self.ws}/pairing',{'name':'No'},outsider).status_code,404)
        self.assertEqual(self.grant(device,client=outsider).status_code,404)
        other=self.workspace('Other workspace')
        self.assertEqual(self.post(f'/workspaces/{other}/devices/{device}/consents',{'capability':'camera_preview','policy_version':devices.POLICY_VERSION,'acknowledged':True}).status_code,404)

    def test_pairing_expiry(self):
        token=self.begin()['token'];self.connection.execute('UPDATE device_pairings SET expires_at=0')
        self.assertEqual(self.approve(token).status_code,404)

    def test_reissue_and_cancel_invalidate_previous_token(self):
        first=self.begin();second=self.begin()
        self.assertEqual(self.approve(first['token']).status_code,404)
        self.assertEqual(self.post(f'/workspaces/{self.ws}/pairing/{second["id"]}/cancel').status_code,200)
        self.assertEqual(self.approve(second['token']).status_code,404)

    def test_other_session_cannot_cancel_pairing(self):
        pairing=self.begin();second=self.app.test_client()
        self.post('/login',{'email':'owner@example.com','password':PASSWORD},second)
        self.assertEqual(self.post(f'/workspaces/{self.ws}/pairing/{pairing["id"]}/cancel',client=second).status_code,404)

    def test_logout_invalidates_pending_pairing(self):
        token=self.begin()['token'];second=self.app.test_client();self.post('/login',{'email':'owner@example.com','password':PASSWORD},second)
        self.post('/logout');self.assertEqual(self.approve(token,second).status_code,404)

    def test_expired_request_session_cannot_be_approved(self):
        token=self.begin()['token'];second=self.app.test_client();self.post('/login',{'email':'owner@example.com','password':PASSWORD},second)
        self.connection.execute('UPDATE account_sessions SET expires_at=0 WHERE id=?',(self.session_id(),))
        self.assertEqual(self.approve(token,second).status_code,401)

    def test_already_paired_browser_cannot_accumulate_enrollments(self):
        self.pair();self.assertEqual(self.post(f'/workspaces/{self.ws}/pairing',{'name':'Duplicate'}).status_code,409)

    def test_consent_requires_correct_policy_and_bool(self):
        device=self.pair()
        self.assertEqual(self.grant(device,policy_version='old').status_code,400)
        for ack in (False,'true',1,None):self.assertEqual(self.grant(device,acknowledged=ack).status_code,400)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents').fetchone()[0],0)

    def test_remote_and_ai_capabilities_cannot_be_granted(self):
        device=self.pair()
        for cap in (*devices.UNAVAILABLE,'*',[],None):
            self.assertEqual(self.grant(device,capability=cap).status_code,403)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents').fetchone()[0],0)

    def test_camera_and_microphone_are_independent_and_expiring(self):
        device=self.pair();grant=self.grant(device).json['grant']
        self.assertLessEqual(grant['expires_at']-grant['server_time'],600)
        url=f'/api/workspaces/{self.ws}/onboarding'
        self.assertEqual([g['capability'] for g in self.client.get(url).json['grants']],['camera_preview'])
        self.assertEqual(self.grant(device,'microphone_preview').status_code,200)
        self.post(f'/workspaces/{self.ws}/devices/{device}/consents/revoke',{'capability':'camera_preview'})
        self.assertEqual([g['capability'] for g in self.client.get(url).json['grants']],['microphone_preview'])
        self.connection.execute('UPDATE preview_consents SET expires_at=0')
        self.assertEqual(self.client.get(url).json['grants'],[])

    def test_preview_ttl_cannot_outlive_account_session(self):
        device=self.pair();now=int(time.time());self.connection.execute('UPDATE account_sessions SET expires_at=?',(now+20,))
        self.assertLessEqual(self.grant(device).json['grant']['expires_at'],now+20)

    def test_other_session_same_account_cannot_grant_or_report(self):
        device=self.pair();other=self.app.test_client();self.post('/login',{'email':'owner@example.com','password':PASSWORD},other)
        self.assertEqual(self.grant(device,client=other).status_code,404)
        self.assertEqual(self.post(f'/workspaces/{self.ws}/devices/{device}/readiness',{'secure_context':True,'media_supported':True,'camera':'unknown','microphone':'unknown'},other).status_code,404)

    def test_admin_cannot_consent_for_member_but_can_revoke(self):
        member,_=self.member(self.ws);device=self.pair(member)
        self.assertEqual(self.grant(device,client=member).status_code,200)
        self.assertEqual(self.grant(device).status_code,404)
        self.assertEqual(self.post(f'/workspaces/{self.ws}/devices/{device}/revoke').status_code,200)
        self.assertEqual(member.get(f'/api/workspaces/{self.ws}/onboarding').json['grants'],[])

    def test_device_revoke_is_idempotent_and_not_reusable(self):
        device=self.pair();self.grant(device)
        url=f'/workspaces/{self.ws}/devices/{device}/revoke'
        self.assertEqual(self.post(url).status_code,200);self.assertEqual(self.post(url).status_code,200)
        self.assertEqual(self.grant(device).status_code,404)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents WHERE revoked_at IS NULL').fetchone()[0],0)

    def test_member_cannot_revoke_another_members_device(self):
        member,_=self.member(self.ws);device=self.pair()
        self.assertEqual(self.post(f'/workspaces/{self.ws}/devices/{device}/revoke',client=member).status_code,404)

    def test_role_change_and_restore_never_resurrects_pairing(self):
        member,uid=self.member(self.ws);device=self.pair(member);self.grant(device,client=member)
        self.post(f'/workspaces/{self.ws}/members/{uid}/role',{'role':'viewer'})
        self.post(f'/workspaces/{self.ws}/members/{uid}/role',{'role':'member'})
        self.assertIsNone(member.get(f'/api/workspaces/{self.ws}/onboarding').json['device'])
        self.assertEqual(self.grant(device,client=member).status_code,404)

    def test_membership_removal_and_rejoin_does_not_restore(self):
        member,uid=self.member(self.ws);device=self.pair(member);self.grant(device,client=member)
        self.post(f'/workspaces/{self.ws}/members/{uid}/remove')
        self.assertEqual(member.get(f'/api/workspaces/{self.ws}/onboarding').status_code,404)
        token=self.invite(self.ws,'member@example.com');self.post('/invitations/accept',{'token':token},member)
        self.assertIsNone(member.get(f'/api/workspaces/{self.ws}/onboarding').json['device'])

    def test_leave_revokes_pairing_and_pending_requests(self):
        member,uid=self.member(self.ws);self.begin(member)
        self.post(f'/workspaces/{self.ws}/leave',client=member)
        self.assertIsNotNone(self.connection.execute('SELECT revoked_at FROM device_pairings WHERE user_id=?',(uid,)).fetchone()[0])

    def test_logout_all_revokes_all_device_consents(self):
        device=self.pair();self.grant(device);self.post('/account/logout-all')
        self.assertEqual(self.connection.execute('SELECT count(*) FROM browser_devices WHERE revoked_at IS NULL').fetchone()[0],0)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents WHERE revoked_at IS NULL').fetchone()[0],0)

    def test_password_reset_revokes_preview_and_pairing(self):
        device=self.pair();self.grant(device);self.post('/password/forgot',{'email':'owner@example.com'})
        self.post('/password/reset',{'token':self.mailbox.token(),'password':PASSWORD+'new'})
        self.assertIsNotNone(self.connection.execute('SELECT revoked_at FROM browser_devices').fetchone()[0])
        self.assertIsNotNone(self.connection.execute('SELECT revoked_at FROM preview_consents').fetchone()[0])

    def test_disable_user_revokes_without_resurrection(self):
        device=self.pair();self.grant(device)
        self.connection.execute('UPDATE users SET disabled_at=? WHERE id=?',(int(time.time()),self.owner))
        self.connection.execute('UPDATE users SET disabled_at=NULL WHERE id=?',(self.owner,))
        self.assertIsNone(self.client.get(f'/api/workspaces/{self.ws}/onboarding').json['device'])

    def test_readiness_accepts_only_bounded_nonidentifying_status_and_grants_nothing(self):
        device=self.pair();url=f'/workspaces/{self.ws}/devices/{device}/readiness'
        report={'secure_context':True,'media_supported':True,'camera':'available','microphone':'unknown'}
        self.assertEqual(self.post(url,report).status_code,200)
        self.assertEqual(self.client.get(f'/api/workspaces/{self.ws}/onboarding').json['grants'],[])
        for data in ({**report,'raw_frame':'data:secret'},{**report,'secure_context':'true'},{**report,'camera':['available']},{**report,'microphone':'recording'}):
            self.assertEqual(self.post(url,data).status_code,400)

    def test_list_hides_other_members_devices_from_regular_members(self):
        member,uid=self.member(self.ws);self.pair();device=self.pair(member)
        rows=devices.list_devices(self.connection,self.ws,uid,self.session_id(member))
        self.assertEqual([r['id'] for r in rows],[device])
        self.assertEqual(len(devices.list_devices(self.connection,self.ws,self.owner,self.session_id())),2)

    def test_pending_pairing_role_change_revokes_token(self):
        member,uid=self.member(self.ws);token=self.begin(member)['token']
        self.post(f'/workspaces/{self.ws}/members/{uid}/role',{'role':'host'})
        self.assertEqual(self.approve(token,member).status_code,404)

    def test_all_new_writes_require_csrf(self):
        device=self.pair()
        for url in (f'/workspaces/{self.ws}/pairing','/device-pairing/inspect','/device-pairing/approve',f'/workspaces/{self.ws}/devices/{device}/consents',f'/workspaces/{self.ws}/devices/{device}/revoke',f'/workspaces/{self.ws}/devices/{device}/readiness'):
            self.assertEqual(self.client.post(url,json={}).status_code,403)

    def test_pair_token_race_yields_exactly_one_device(self):
        token=self.begin()['token'];session=self.session_id()
        def attempt(_):
            con=self.store.connect()
            try:
                devices.approve_pairing(con,self.owner,session,token);return True
            except PlatformError:return False
            finally:con.close()
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(attempt,range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM browser_devices').fetchone()[0],1)

    def test_invalidated_device_cannot_issue_consent(self):
        device=self.pair();session_id=self.session_id();self.connection.execute('UPDATE account_sessions SET revoked_at=?',(int(time.time()),))
        with self.assertRaises(PlatformError):devices.grant_preview(self.connection,self.ws,device,self.owner,session_id, 'camera_preview',devices.POLICY_VERSION,True)

    def test_audit_does_not_record_pairing_bearer_or_readiness_payload(self):
        token=self.begin()['token'];self.approve(token)
        serialized=str([dict(row) for row in self.connection.execute('SELECT * FROM audit_events')])
        self.assertNotIn(token,serialized)
        self.assertNotIn('media_supported',serialized)

    def test_migration_preserves_v1_accounts_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.sqlite3';con=sqlite3.connect(path)
            con.executescript(SCHEMA)
            con.execute('INSERT INTO schema_migrations VALUES (1,1)')
            con.execute("INSERT INTO users VALUES ('old','old@example.com','Old','hash',1,NULL,1)")
            con.commit();con.close()
            Store(path);Store(path);con=sqlite3.connect(path)
            self.assertEqual(con.execute('SELECT display_name FROM users').fetchone()[0],'Old')
            self.assertEqual([r[0] for r in con.execute('SELECT version FROM schema_migrations ORDER BY version')],[1,2]);con.close()

    def test_pair_limit_bounds_active_sessions(self):
        from platform_core.security import token_hash, opaque_token
        from platform_core.store import new_id
        now=int(time.time())
        for _ in range(10):
            session=new_id();self.connection.execute('INSERT INTO account_sessions VALUES (?,?,?,?,?,?,NULL)',(session,self.owner,token_hash(opaque_token()),now,now,now+28800))
            pairing=devices.begin_pairing(self.connection,self.ws,self.owner,session,'Fixture')
            devices.approve_pairing(self.connection,self.owner,session,pairing['token'])
        token=self.begin()['token']
        self.assertEqual(self.approve(token).status_code,409)

    def test_grant_race_with_revoke_never_leaves_active_consent(self):
        device=self.pair();session=self.session_id()
        def attempt(kind):
            con=self.store.connect()
            try:
                if kind=='revoke':devices.revoke_device(con,self.ws,device,self.owner)
                else:devices.grant_preview(con,self.ws,device,self.owner,session,'camera_preview',devices.POLICY_VERSION,True)
            except PlatformError:pass
            finally:con.close()
        with ThreadPoolExecutor(max_workers=2) as executor:list(executor.map(attempt,('grant','revoke')))
        self.assertEqual(self.connection.execute('SELECT count(*) FROM preview_consents WHERE revoked_at IS NULL').fetchone()[0],0)

    def test_idle_session_and_ownership_transfer_fail_closed(self):
        device=self.pair();self.grant(device)
        member,uid=self.member(self.ws)
        self.post(f'/workspaces/{self.ws}/ownership',{'member_id':uid,'password':PASSWORD})
        self.assertIsNone(self.client.get(f'/api/workspaces/{self.ws}/onboarding').json['device'])
        own=self.pair();session=self.session_id()
        self.connection.execute('UPDATE account_sessions SET last_seen_at=0 WHERE id=?',(session,))
        with self.assertRaises(PlatformError):devices.grant_preview(self.connection,self.ws,own,self.owner,session,'camera_preview',devices.POLICY_VERSION,True)

    def test_browser_name_is_escaped_and_untrusted(self):
        token=self.begin(name='<img src=x onerror=alert(1)>')['token'];self.approve(token)
        page=self.client.get(f'/workspaces/{self.ws}/onboarding').text
        self.assertIn('&lt;img',page);self.assertNotIn('<img src=x',page)
