import json
import unittest

from app.jood_ai import (
    JoodAIError,
    build_vertex_payload,
    extract_vertex_text,
    generate_jood_reply,
)
from app.jood_identity import should_jood_ai_reply


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class SequenceOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout=0):
        self.requests.append((request, timeout))
        return FakeResponse(self.payloads.pop(0))


class JoodAITests(unittest.TestCase):
    def test_reply_scope_direct_and_group(self):
        self.assertTrue(should_jood_ai_reply("السلام عليكم", "966500000000@s.whatsapp.net"))
        self.assertTrue(should_jood_ai_reply("يا جود عندي سؤال", "120363000000@g.us"))
        self.assertTrue(should_jood_ai_reply("Jood can you help?", "120363000000@g.us"))
        self.assertTrue(should_jood_ai_reply("عندي سؤال", "120363000000@g.us"))
        self.assertTrue(should_jood_ai_reply("مين انتم", "120363000000@g.us"))
        self.assertTrue(should_jood_ai_reply("مرحبا", "120363000000@g.us"))
        self.assertFalse(should_jood_ai_reply("", "966500000000@s.whatsapp.net"))

    def test_vertex_payload_uses_dynamic_few_shot_and_keeps_live_message_last(self):
        customer_text = "جود، عرفيني عن بكجات بجملة واحدة"
        payload = build_vertex_payload(customer_text)
        self.assertIn("systemInstruction", payload)
        roles = [item["role"] for item in payload["contents"]]
        self.assertGreaterEqual(roles.count("model"), 3)
        self.assertEqual(payload["contents"][-1]["role"], "user")
        self.assertEqual(payload["contents"][-1]["parts"][0]["text"], customer_text)

    def test_prompt_contains_role_rules_but_no_fixed_pakgat_answer(self):
        payload = build_vertex_payload("عرفيني عن بكجات")
        system_text = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("B2C", system_text)
        self.assertIn("B2B", system_text)
        self.assertIn("المبيعات", system_text)
        self.assertIn("لا تنسخي", system_text)
        self.assertIn("https://pakgat.com/ar", system_text)
        self.assertNotIn(
            "بكجات منصة سعودية تجمع لك بكجات وكوبونات وعروض وتجارب مختارة في الرياض وتسهّل شراءها واستخدامها رقميًا",
            system_text,
        )

    def test_few_shot_examples_are_style_guidance_not_unverified_offers(self):
        payload = build_vertex_payload("أبغى عرض")
        serialized = json.dumps(payload["contents"][:-1], ensure_ascii=False)
        self.assertNotIn("50%", serialized)
        self.assertNotIn("خصم حصري لمشتركينا", serialized)
        self.assertNotIn("نفاد الكمية", serialized)
        self.assertIn("pakgat.com/ar", serialized)

    def test_generation_config_keeps_responses_varied_but_controlled(self):
        payload = build_vertex_payload("مرحبا")
        self.assertEqual(payload["generationConfig"]["temperature"], 0.5)
        self.assertEqual(payload["generationConfig"]["topP"], 0.95)

    def test_extract_vertex_text(self):
        data = {"candidates": [{"content": {"parts": [{"text": "أهلًا"}, {"text": " بك"}]}}]}
        self.assertEqual(extract_vertex_text(data), "أهلًا بك")
        with self.assertRaises(JoodAIError):
            extract_vertex_text({"candidates": []})

    def test_generate_jood_reply_uses_metadata_token_then_vertex(self):
        opener = SequenceOpener([
            {"access_token": "token-1"},
            {"candidates": [{"content": {"parts": [{"text": "حياك الله، كيف أقدر أخدمك؟"}]}}]},
        ])
        text = generate_jood_reply("مرحبا جود", opener=opener)
        self.assertEqual(text, "حياك الله، كيف أقدر أخدمك؟")
        self.assertEqual(len(opener.requests), 2)
        metadata_req = opener.requests[0][0]
        vertex_req = opener.requests[1][0]
        self.assertIn("metadata.google.internal", metadata_req.full_url)
        self.assertEqual(metadata_req.headers.get("Metadata-flavor"), "Google")
        self.assertIn("aiplatform.googleapis.com", vertex_req.full_url)
        self.assertEqual(vertex_req.headers.get("Authorization"), "Bearer token-1")


if __name__ == "__main__":
    unittest.main()
