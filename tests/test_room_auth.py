import os
import unittest

from services.room_auth import issue_room_token, verify_room_token


class RoomAuthTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get("WEBRTC_SECRET_KEY")
        os.environ["WEBRTC_SECRET_KEY"] = "x" * 64

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("WEBRTC_SECRET_KEY", None)
        else:
            os.environ["WEBRTC_SECRET_KEY"] = self.previous

    def test_token_round_trip(self):
        token = issue_room_token("room-1", "user-1", "client")
        claims = verify_room_token(token, "room-1", "user-1")
        self.assertEqual(claims["role"], "client")

    def test_wrong_room_is_rejected(self):
        token = issue_room_token("room-1", "user-1")
        with self.assertRaises(ValueError):
            verify_room_token(token, "room-2")

    def test_agent_role_is_supported(self):
        token = issue_room_token("room-1", "workstation-1", "agent")
        claims = verify_room_token(token, "room-1", "workstation-1")
        self.assertEqual(claims["role"], "agent")

    def test_malformed_base64_is_rejected_as_value_error(self):
        with self.assertRaises(ValueError):
            verify_room_token("not-valid-base64.abc", "room-1")


if __name__ == "__main__":
    unittest.main()