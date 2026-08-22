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
        self.assertFalse(should_jood_ai_reply("عندي سؤال", "120363000000@g.us"))
        self.assertFalse(should_jood_ai_reply("", "966500000000@s.whatsapp.net"))

    def test_vertex_payload_contains_identity_and_customer_text(self):
        payload = build_vertex_payload("أبغى أعرف عن بكجات")
        self.assertIn("systemInstruction", payload)
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "أبغى أعرف عن بكجات")

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
