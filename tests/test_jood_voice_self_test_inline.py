import unittest

from app.jood_voice_self_test_inline import (
    OLD_SELF_TEST_HANDLER,
    build_inline_local_self_test_handler,
    rewrite_live_self_test_html,
)


class JoodInlineLocalSelfTestTests(unittest.TestCase):
    def test_inline_handler_selects_physical_sink_and_exposes_diagnostics(self):
        handler = build_inline_local_self_test_handler()
        self.assertIn("navigator.mediaDevices.enumerateDevices", handler)
        self.assertIn("audiooutput", handler)
        self.assertIn("setSinkId", handler)
        self.assertIn("new Audio", handler)
        self.assertIn("realtek", handler.lower())
        self.assertIn("lg ultrafine", handler.lower())
        self.assertIn("voicemeeter", handler.lower())
        self.assertIn("motorola", handler.lower())
        self.assertIn("TTS HTTP", handler)
        self.assertIn("Audio Bytes", handler)
        self.assertIn("Selected Sink", handler)
        self.assertIn("Audio Decode", handler)
        self.assertIn("Playback State", handler)
        self.assertIn("ended", handler.lower())
        self.assertNotIn("await speakReply", handler)
        self.assertNotIn("startCall", handler)

    def test_rewrite_replaces_the_known_live_self_test_handler_in_place(self):
        html = "<script>before\n" + OLD_SELF_TEST_HANDLER + "\nafter</script>"
        rewritten = rewrite_live_self_test_html(html)
        self.assertNotIn(OLD_SELF_TEST_HANDLER, rewritten)
        self.assertIn("اختبار محلي لصوت جود", rewritten)
        self.assertIn("setSinkId", rewritten)
        self.assertIn("local-self-test-diagnostics", rewritten)

    def test_rewrite_fails_closed_when_expected_handler_is_missing(self):
        with self.assertRaises(RuntimeError):
            rewrite_live_self_test_html("<html><body>unexpected live bridge</body></html>")


if __name__ == "__main__":
    unittest.main()
