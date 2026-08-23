import json
import unittest

from app.jood_ai import JOOD_RESPONSE_SCHEMA, build_vertex_payload, extract_jood_decision
from app.jood_reply_validation import validate_and_clean_reply


class JoodStructuredDialogueTests(unittest.TestCase):
    def test_schema_requires_sales_decision_fields(self):
        required = set(JOOD_RESPONSE_SCHEMA["required"])
        self.assertEqual(
            required,
            {"reply", "detected_intent", "next_stage", "last_commitment_fulfilled", "handoff_required"},
        )

    def test_structured_payload_uses_vertex_json_schema(self):
        payload = build_vertex_payload("تمام", structured_output=True)
        config = payload["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseSchema"], JOOD_RESPONSE_SCHEMA)

    def test_extracts_structured_decision_from_vertex_candidate(self):
        decision = {
            "reply": "هذه تفاصيل العروض: https://pakgat.com/ar. ما الفئة التي تهمك؟",
            "detected_intent": "accepted_offer",
            "next_stage": "details_shared",
            "last_commitment_fulfilled": True,
            "handoff_required": False,
        }
        payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(decision, ensure_ascii=False)}]}}]}
        self.assertEqual(extract_jood_decision(payload), decision)

    def test_cleans_markdown_and_deduplicates_approved_url(self):
        result = validate_and_clean_reply(
            "تفضل https://pakgat.com/ar](https://pakgat.com/ar) https://pakgat.com/ar.",
            direction="outbound",
            last_commitment="إرسال الرابط",
            commitment_fulfilled=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reply.count("https://pakgat.com/ar"), 1)
        self.assertNotIn("](", result.reply)

    def test_rejects_truncated_or_inbound_reset_reply(self):
        truncated = validate_and_clean_reply(
            "تمام، يسعدني ذلك. بك",
            direction="outbound",
            last_commitment="إرسال التفاصيل",
            commitment_fulfilled=False,
        )
        self.assertFalse(truncated.ok)
        reset = validate_and_clean_reply(
            "أهلًا بك، كيف أساعدك؟",
            direction="outbound",
            last_commitment="",
            commitment_fulfilled=True,
        )
        self.assertFalse(reset.ok)

    def test_rejects_unapproved_url(self):
        result = validate_and_clean_reply(
            "شاهد العرض هنا https://pakgat.com/fake-offer.",
            direction="outbound",
            last_commitment="إرسال العرض",
            commitment_fulfilled=True,
        )
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
