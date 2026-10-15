import unittest

from WebRTC_Meet.room_store import RoomStore


class RoomStoreTests(unittest.TestCase):
    def test_local_store_round_trip(self):
        store = RoomStore(None, "test-room")
        self.assertFalse(store.shared)
        self.assertFalse(store.healthy())
        store.set("meeting_locked", True)
        self.assertTrue(store.get("meeting_locked"))
        store.set("items", [{"id": 1}])
        self.assertEqual(store.get("items"), [{"id": 1}])
        store.delete("items")
        self.assertIsNone(store.get("items"))

    def test_local_update_is_atomic_under_store_lock(self):
        store = RoomStore(None, "test-room")
        store.set("counter", 0)
        value = store.update("counter", lambda current: int(current or 0) + 1, default=0)
        self.assertEqual(value, 1)
        self.assertEqual(store.get("counter"), 1)



class LocalTTLTests(unittest.TestCase):
    def test_local_request_expiry_and_cleanup(self):
        from unittest.mock import patch
        from WebRTC_Meet.room_store import RoomStore
        store = RoomStore(None, 'ttl-test')
        with patch('WebRTC_Meet.room_store.time.monotonic', return_value=10):
            store.set('request', {'payload': 'fixture'}, ttl=1)
        with patch('WebRTC_Meet.room_store.time.monotonic', return_value=12):
            self.assertIsNone(store.get('request'))
        with patch('WebRTC_Meet.room_store.time.monotonic', return_value=20):
            store.set('new', 1)
        self.assertNotIn('request', store._local)

if __name__ == "__main__":
    unittest.main()