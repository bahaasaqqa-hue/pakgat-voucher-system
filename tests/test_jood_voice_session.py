import unittest

from app.jood_voice_bridge_ui import (
    append_transcript_line,
    outcome_flags,
)


class JoodVoiceSessionTests(unittest.TestCase):
    def test_transcript_accumulates_customer_and_jood_turns(self):
        transcript = append_transcript_line("", "customer", "السلام عليكم")
        transcript = append_transcript_line(transcript, "jood", "وعليكم السلام")
        self.assertEqual(transcript.splitlines(), ["CUSTOMER: السلام عليكم", "JOOD: وعليكم السلام"])

    def test_interested_requires_follow_up_but_not_do_not_contact(self):
        follow_up, blocked = outcome_flags("interested")
        self.assertTrue(follow_up)
        self.assertFalse(blocked)

    def test_do_not_contact_blocks_future_outbound(self):
        follow_up, blocked = outcome_flags("do_not_contact")
        self.assertFalse(follow_up)
        self.assertTrue(blocked)

    def test_handoff_requires_follow_up(self):
        follow_up, blocked = outcome_flags("human_handoff")
        self.assertTrue(follow_up)
        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
