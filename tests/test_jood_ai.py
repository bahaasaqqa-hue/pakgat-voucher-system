import json
import unittest

from app.jood_ai import (
    JoodAIError,
    build_vertex_payload,
    extract_vertex_text,
    generate_jood_reply,
)
from app.jood_identity import JOOD_SYSTEM_PROMPT, should_jood_ai_reply
from app.whatsloop_inbound_core import normalize_inbound_event


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
    def test_reply_scope_is_private_chat_only(self):
        self.assertTrue(should_jood_ai_reply("السلام عليكم", "966500000000@s.whatsapp.net"))
        self.assertFalse(should_jood_ai_reply("يا جود عندي سؤال", "120363000000@g.us"))
        self.assertFalse(should_jood_ai_reply("", "966500000000@s.whatsapp.net"))
        self.assertFalse(should_jood_ai_reply("مرحبا", None))

    def test_direct_whatsloop_message_uses_sender_when_chat_id_is_missing(self):
        payload = {
            "event": "message.received",
            "data": {
                "object": {
                    "id": "msg-direct-1",
                    "phone": "966500000000@s.whatsapp.net",
                    "content": "مرحبا جود",
                    "from_me": False,
                },
                "channel_id": 7,
            },
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        event = normalize_inbound_event(payload, raw)
        self.assertEqual(event.sender, "966500000000@s.whatsapp.net")
        self.assertEqual(event.chat_id, event.sender)
        self.assertTrue(should_jood_ai_reply(event.text, event.chat_id))

    def test_group_whatsloop_message_is_never_routed_to_jood(self):
        payload = {
            "event": "message.received",
            "data": {
                "object": {
                    "id": "msg-group-1",
                    "phone": "966500000000@s.whatsapp.net",
                    "group_id": "120363000000@g.us",
                    "content": "يا جود عندي سؤال",
                    "from_me": False,
                },
                "channel_id": 7,
            },
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        event = normalize_inbound_event(payload, raw)
        self.assertEqual(event.chat_id, "120363000000@g.us")
        self.assertFalse(should_jood_ai_reply(event.text, event.chat_id))

    def test_out_of_scope_instruction_is_short_and_does_not_answer_topic(self):
        self.assertIn("لا تجيبي عن موضوعه", JOOD_SYSTEM_PROMPT)
        self.assertIn("بجملة واحدة قصيرة", JOOD_SYSTEM_PROMPT)

    def test_vertex_payload_contains_only_real_history_and_current_message(self):
        history = [
            {"role": "user", "text": "أبغى عروض العناية بالسيارات"},
            {"role": "model", "text": "أكيد، هذا القسم المعتمد."},
            {"role": "user", "text": "أنا اسمي بهاء"},
            {"role": "model", "text": "تشرفنا يا بهاء."},
        ]
        customer_text = "كيف نظام القسائم عندكم"
        payload = build_vertex_payload(customer_text, history=history, mode="customer", intent="order_or_voucher")
        contents = payload["contents"]
        self.assertEqual([item["role"] for item in contents], ["user", "model", "user", "model", "user"])
        self.assertEqual(contents[-1]["parts"][0]["text"], customer_text)
        serialized = json.dumps(contents, ensure_ascii=False)
        self.assertNotIn("payment problem", serialized.lower())
        self.assertNotIn("نحن مركز سبا", serialized)

    def test_history_is_limited_to_last_eight_real_turns(self):
        history = [
            {"role": "user" if i % 2 == 0 else "model", "text": f"turn-{i}"}
            for i in range(12)
        ]
        payload = build_vertex_payload("current", history=history)
        previous = payload["contents"][:-1]
        self.assertEqual(len(previous), 8)
        self.assertEqual(previous[0]["parts"][0]["text"], "turn-4")
        self.assertEqual(previous[-1]["parts"][0]["text"], "turn-11")

    def test_style_examples_live_only_in_system_instruction(self):
        payload = build_vertex_payload("أبغى عرض")
        self.assertEqual(len(payload["contents"]), 1)
        system_text = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("أمثلة أسلوب", system_text)
        self.assertIn("الكوبون", system_text)
        self.assertIn("B2B", system_text)

    def test_runtime_context_contains_company_mode_and_intent(self):
        payload = build_vertex_payload("عندنا مطعم", mode="merchant", intent="merchant_prospecting")
        system_text = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("Company AI mode: merchant", system_text)
        self.assertIn("Current intent: merchant_prospecting", system_text)

    def test_prompt_contains_role_rules_but_no_fixed_pakgat_answer(self):
        payload = build_vertex_payload("عرفيني عن بكجات")
        system_text = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("B2C", system_text)
        self.assertIn("B2B", system_text)
        self.assertIn("المبيعات", system_text)
        self.assertIn("https://pakgat.com/ar", system_text)
        self.assertNotIn(
            "بكجات منصة سعودية تجمع لك بكجات وكوبونات وعروض وتجارب مختارة في الرياض وتسهّل شراءها واستخدامها رقميًا",
            system_text,
        )

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
        text = generate_jood_reply(
            "مرحبا جود",
            history=[{"role": "user", "text": "سلام"}],
            mode="customer",
            intent="general",
            opener=opener,
        )
        self.assertEqual(text, "حياك الله، كيف أقدر أخدمك؟")
        self.assertEqual(len(opener.requests), 2)
        metadata_req = opener.requests[0][0]
        vertex_req = opener.requests[1][0]
        self.assertIn("metadata.google.internal", metadata_req.full_url)
        self.assertEqual(metadata_req.headers.get("Metadata-flavor"), "Google")
        self.assertIn("aiplatform.googleapis.com", vertex_req.full_url)
        self.assertEqual(vertex_req.headers.get("Authorization"), "Bearer token-1")
        body = json.loads(vertex_req.data.decode("utf-8"))
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "سلام")
        self.assertEqual(body["contents"][-1]["parts"][0]["text"], "مرحبا جود")


if __name__ == "__main__":
    unittest.main()
