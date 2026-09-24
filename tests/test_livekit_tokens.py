import base64
import json
import os
import unittest

from services.livekit_tokens import issue_livekit_token


class LiveKitTokenTests(unittest.TestCase):
    def setUp(self):
        os.environ["LIVEKIT_API_KEY"] = "devkey"
        os.environ["LIVEKIT_API_SECRET"] = "x" * 32

    def tearDown(self):
        os.environ.pop("LIVEKIT_API_KEY", None)
        os.environ.pop("LIVEKIT_API_SECRET", None)

    def test_token_contains_room_grant(self):
        token = issue_livekit_token("room-1", "user-1")
        payload = token.split(".")[1] + "=="
        claims = json.loads(base64.urlsafe_b64decode(payload))
        self.assertEqual(claims["iss"], "devkey")
        self.assertEqual(claims["video"]["room"], "room-1")


if __name__ == "__main__":
    unittest.main()