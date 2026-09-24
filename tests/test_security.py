import unittest

from utils.security import MajorityVote, SlidingWindowRateLimiter, safe_face_name


class SecurityUtilityTests(unittest.TestCase):
    def test_face_names_are_safe_and_bounded(self):
        self.assertEqual(safe_face_name("../../Alice Smith"), "Alice_Smith")
        self.assertEqual(safe_face_name(""), "user_default")
        self.assertLessEqual(len(safe_face_name("x" * 200)), 64)

    def test_majority_vote_stabilizes_transient_identity(self):
        vote = MajorityVote(size=5)
        vote.add("Alice")
        vote.add("Alice")
        self.assertEqual(vote.add("Unknown"), "Alice")
        vote.add("Unknown")
        self.assertEqual(vote.add("Unknown"), "Unknown")

    def test_rate_limiter_rejects_burst_and_recovers(self):
        limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=0.02)
        self.assertTrue(limiter.allow("client-1"))
        self.assertTrue(limiter.allow("client-1"))
        self.assertFalse(limiter.allow("client-1"))
        import time
        time.sleep(0.03)
        self.assertTrue(limiter.allow("client-1"))


if __name__ == "__main__":
    unittest.main()