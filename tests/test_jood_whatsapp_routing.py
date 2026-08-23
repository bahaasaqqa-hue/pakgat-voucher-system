import json
import unittest

from app.jood_identity import should_jood_ai_reply
from app.whatsloop_inbound_core import normalize_inbound_event


def _normalize(data_object):
    payload = {
        "type": "message.received",
        "data": {"object": data_object},
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return normalize_inbound_event(payload, raw)


class JoodWhatsAppRoutingTests(unittest.TestCase):
    def test_private_message_uses_sender_as_reply_destination(self):
        event = _normalize(
            {
                "message_id": "private-1",
                "channel_id": 5,
                "phone": "966500001514",
                "content": "من وين",
                "from_me": False,
            }
        )

        self.assertEqual(event.sender, "966500001514")
        self.assertEqual(event.chat_id, "966500001514")
        self.assertTrue(should_jood_ai_reply(event.text, event.chat_id))

    def test_group_message_is_not_eligible_for_jood_auto_reply(self):
        event = _normalize(
            {
                "message_id": "group-1",
                "channel_id": 5,
                "phone": "966500001514",
                "group_id": "120363429327806767@g.us",
                "content": "عرض سينما لا يخص بكجات",
                "from_me": False,
            }
        )

        self.assertEqual(event.chat_id, "120363429327806767@g.us")
        self.assertFalse(should_jood_ai_reply(event.text, event.chat_id))

    def test_empty_private_message_is_not_eligible_for_reply(self):
        self.assertFalse(should_jood_ai_reply("", "966500001514"))
        self.assertFalse(should_jood_ai_reply("   ", "966500001514"))


if __name__ == "__main__":
    unittest.main()
