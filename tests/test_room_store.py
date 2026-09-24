import unittest

from WebRTC_Meet.room_store import RoomStore


class RoomStoreTests(unittest.TestCase):
    def test_local_store_round_trip(self):
        store = RoomStore(None, "test-room")
        store.set("meeting_locked", True)
        self.assertTrue(store.get("meeting_locked"))
        store.set("items", [{"id": 1}])
        self.assertEqual(store.get("items"), [{"id": 1}])
        store.delete("items")
        self.assertIsNone(store.get("items"))


if __name__ == "__main__":
    unittest.main()