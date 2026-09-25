import os
import time
import unittest

os.environ.setdefault("WEBRTC_SECRET_KEY", "s" * 64)
os.environ.setdefault("WEBRTC_ADMIN_TOKEN", "admin-test")
os.environ.setdefault("WEBRTC_REQUIRE_JOIN_TOKEN", "true")
os.environ.setdefault("LIVEKIT_API_KEY", "devkey")
os.environ.setdefault("LIVEKIT_API_SECRET", "k" * 32)

from services.room_auth import issue_room_token
from WebRTC_Meet import app as signaling
from desktop_agent import _claim_command, _seen_command_ids, _seen_command_lock


class SignalingContractTests(unittest.TestCase):
    def setUp(self):
        self.previous_livekit_key = os.environ.get("LIVEKIT_API_KEY")
        self.previous_livekit_secret = os.environ.get("LIVEKIT_API_SECRET")
        os.environ["LIVEKIT_API_KEY"] = "devkey"
        os.environ["LIVEKIT_API_SECRET"] = "k" * 32
        signaling.participants.clear()
        signaling.room_store.delete("meeting_locked")

    def tearDown(self):
        signaling.participants.clear()
        signaling.room_store.delete("meeting_locked")
        if self.previous_livekit_key is None:
            os.environ.pop("LIVEKIT_API_KEY", None)
        else:
            os.environ["LIVEKIT_API_KEY"] = self.previous_livekit_key
        if self.previous_livekit_secret is None:
            os.environ.pop("LIVEKIT_API_SECRET", None)
        else:
            os.environ["LIVEKIT_API_SECRET"] = self.previous_livekit_secret

    def _ticket(self, identity, role):
        return issue_room_token(signaling.ROOM_NAME, identity, role, ttl=300)

    def test_health_headers_and_shared_state_readiness(self):
        client = signaling.app.test_client()
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

        previous = signaling.REQUIRE_SHARED_STATE
        signaling.REQUIRE_SHARED_STATE = True
        try:
            self.assertEqual(client.get("/readyz").status_code, 503)
        finally:
            signaling.REQUIRE_SHARED_STATE = previous

    def test_livekit_page_is_available_as_opt_in_media_path(self):
        response = signaling.app.test_client().get("/livekit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"LiveKit Room", response.data)

    def test_local_socketio_client_asset_is_available(self):
        response = signaling.app.test_client().get(
            "/static/vendor/socket.io-4.5.4.js"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Socket.IO v4.5.4", response.data)

    def test_room_token_requires_admin(self):
        client = signaling.app.test_client()
        self.assertEqual(
            client.post(
                "/api/room-token",
                headers={"X-Admin-Token": "wrong"},
                json={"identity": "client-1"},
            ).status_code,
            401,
        )
        response = client.post(
            "/api/room-token",
            headers={"X-Admin-Token": "admin-test"},
            json={"identity": "client-1", "room": "different-room"},
        )
        self.assertEqual(response.status_code, 400)

    def test_livekit_token_exchange_uses_room_token(self):
        client = signaling.app.test_client()
        self.assertEqual(
            client.post("/api/livekit-token", json={}).status_code,
            401,
        )
        response = client.post(
            "/api/livekit-token",
            json={"join_token": self._ticket("client-1", "client")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["livekit_token"])
        self.assertEqual(response.json["identity"], "client-1")

    def test_admin_and_client_join_and_caption_identity(self):
        http = signaling.app.test_client()
        admin = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        admin.emit(
            "join",
            {
                "role": "admin",
                "identity": "admin-dashboard",
                "name": "Admin",
                "join_token": self._ticket("admin-dashboard", "admin"),
            },
        )
        self.assertFalse(
            any(event["name"] == "join_rejected" for event in admin.get_received())
        )

        client = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        client.emit(
            "join",
            {
                "role": "client",
                "identity": "client-1",
                "name": "Alice",
                "join_token": self._ticket("client-1", "client"),
            },
        )
        self.assertFalse(
            any(event["name"] == "join_rejected" for event in client.get_received())
        )

        client.emit("live_caption", {"name": "Spoof", "text": "hello"})
        captions = [
            event
            for event in admin.get_received()
            if event["name"] == "caption_broadcast"
        ]
        self.assertEqual(captions[-1]["args"][0], {"name": "Alice", "text": "hello"})

        client.emit("chat_message", None)
        client.emit("whiteboard_draw", None)
        admin.disconnect()
        client.disconnect()

    def test_invalid_token_and_locked_room_are_rejected(self):
        http = signaling.app.test_client()
        invalid = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        invalid.emit(
            "join",
            {"role": "client", "identity": "bad", "name": "Bad", "join_token": ""},
        )
        self.assertTrue(
            any(event["name"] == "join_rejected" for event in invalid.get_received())
        )
        invalid.disconnect()

        admin = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        admin.emit(
            "join",
            {
                "role": "admin",
                "identity": "admin-dashboard",
                "name": "Admin",
                "join_token": self._ticket("admin-dashboard", "admin"),
            },
        )
        admin.get_received()
        admin.emit("toggle_meeting_lock", {"locked": True})

        locked = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        locked.emit(
            "join",
            {
                "role": "client",
                "identity": "locked",
                "name": "Locked",
                "join_token": self._ticket("locked", "client"),
            },
        )
        self.assertTrue(
            any(event["name"] == "join_rejected" for event in locked.get_received())
        )
        admin.disconnect()
        locked.disconnect()

    def test_participant_capacity_is_enforced(self):
        previous = signaling.MAX_PARTICIPANTS
        signaling.MAX_PARTICIPANTS = 1
        try:
            http = signaling.app.test_client()
            first = signaling.socketio.test_client(signaling.app, flask_test_client=http)
            first.emit(
                "join",
                {
                    "role": "client",
                    "identity": "capacity-1",
                    "name": "Capacity 1",
                    "join_token": self._ticket("capacity-1", "client"),
                },
            )
            self.assertFalse(
                any(event["name"] == "join_rejected" for event in first.get_received())
            )
            second = signaling.socketio.test_client(signaling.app, flask_test_client=http)
            second.emit(
                "join",
                {
                    "role": "client",
                    "identity": "capacity-2",
                    "name": "Capacity 2",
                    "join_token": self._ticket("capacity-2", "client"),
                },
            )
            self.assertTrue(
                any(event["name"] == "join_rejected" for event in second.get_received())
            )
            first.disconnect()
            second.disconnect()
        finally:
            signaling.MAX_PARTICIPANTS = previous

    def test_remote_desktop_requires_a_connected_client_target(self):
        http = signaling.app.test_client()
        admin = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        admin.emit(
            "join",
            {
                "role": "admin",
                "identity": "remote-admin",
                "name": "Remote Admin",
                "join_token": self._ticket("remote-admin", "admin"),
            },
        )
        admin.get_received()

        admin.emit("desktop_quick_action", {"action": "lock_workstation"})
        errors = [
            event
            for event in admin.get_received()
            if event["name"] == "desktop_action_result"
        ]
        self.assertTrue(errors)
        self.assertEqual(errors[-1]["args"][0]["status"], "error")

        client = signaling.socketio.test_client(signaling.app, flask_test_client=http)
        client.emit(
            "join",
            {
                "role": "client",
                "identity": "remote-client",
                "name": "Remote Client",
                "join_token": self._ticket("remote-client", "client"),
            },
        )
        client.get_received()
        client_sid = next(
            sid
            for sid, user in signaling.participants.items()
            if user.get("identity") == "remote-client"
        )

        admin.emit(
            "desktop_quick_action",
            {"target": client_sid, "action": "lock_workstation"},
        )
        errors = [
            event
            for event in admin.get_received()
            if event["name"] == "desktop_action_result"
        ]
        self.assertTrue(errors)
        self.assertIn("paired desktop agent", errors[-1]["args"][0]["msg"])

        admin.emit(
            "admin_remote_command",
            {
                "target": client_sid,
                "command": "open_url",
                "payload": {"url": "javascript:alert(1)"},
            },
        )
        errors = [
            event
            for event in admin.get_received()
            if event["name"] == "desktop_action_result"
        ]
        self.assertTrue(errors)
        self.assertIn("valid HTTP(S)", errors[-1]["args"][0]["msg"])

        admin.disconnect()
        client.disconnect()

    def test_desktop_command_expiry_and_replay_protection(self):
        with _seen_command_lock:
            _seen_command_ids.clear()
        command = {"request_id": "abc123", "expires_at": time.time() + 1}
        self.assertEqual(_claim_command(command), "abc123")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            _claim_command(command)
        with self.assertRaisesRegex(ValueError, "expired"):
            _claim_command(
                {"request_id": "expired", "expires_at": time.time() - 1}
            )

    def test_participant_state_is_room_scoped(self):
        from WebRTC_Meet.shared_state import SharedParticipants

        first = SharedParticipants(None, "room-a")
        second = SharedParticipants(None, "room-b")
        self.assertNotEqual(first._prefix, second._prefix)


if __name__ == "__main__":
    unittest.main()