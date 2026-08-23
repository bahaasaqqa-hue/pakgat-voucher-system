import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.jood_company_ops import (
    CALL_COOLDOWN_SECONDS,
    call_window_is_open,
    cooldown_is_satisfied,
    conversation_key_for,
)


class JoodCallOpsTests(unittest.TestCase):
    def test_fixed_cooldown_is_30_seconds(self):
        self.assertEqual(CALL_COOLDOWN_SECONDS, 30)

    def test_call_window_is_open_only_between_start_and_end(self):
        start = datetime(2026, 8, 23, 7, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)
        campaign = SimpleNamespace(start_at=start, end_at=end, status="active")
        self.assertTrue(call_window_is_open(campaign, start + timedelta(minutes=10)))
        self.assertFalse(call_window_is_open(campaign, start - timedelta(seconds=1)))
        self.assertFalse(call_window_is_open(campaign, end + timedelta(seconds=1)))

    def test_paused_campaign_is_not_open(self):
        now = datetime.now(timezone.utc)
        campaign = SimpleNamespace(start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1), status="paused")
        self.assertFalse(call_window_is_open(campaign, now))

    def test_cooldown_requires_30_seconds_after_last_finished_call(self):
        now = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
        self.assertTrue(cooldown_is_satisfied(None, now))
        self.assertFalse(cooldown_is_satisfied(now - timedelta(seconds=29), now))
        self.assertTrue(cooldown_is_satisfied(now - timedelta(seconds=30), now))

    def test_group_conversation_key_isolated_by_sender(self):
        a = conversation_key_for("whatsapp", 1, chat_id="120363@g.us", sender="966500000001")
        b = conversation_key_for("whatsapp", 2, chat_id="120363@g.us", sender="966500000002")
        self.assertNotEqual(a, b)
        self.assertIn("966500000001", a)
        self.assertIn("966500000002", b)


if __name__ == "__main__":
    unittest.main()
