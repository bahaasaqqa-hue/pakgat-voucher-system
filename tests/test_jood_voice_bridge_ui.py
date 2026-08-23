import unittest

from app.jood_voice_bridge_ui import build_voice_bridge_script, initial_voice_opening


class JoodVoiceBridgeUITests(unittest.TestCase):
    def test_bridge_routes_recognition_from_voicemeeter_b1_track(self):
        script = build_voice_bridge_script(42)
        self.assertIn("navigator.mediaDevices.enumerateDevices", script)
        self.assertIn("Voicemeeter", script)
        self.assertIn("B1", script)
        self.assertIn("recognition.start(audioTrack)", script)
        self.assertNotIn("recognition.start();", script)

    def test_bridge_speaks_opening_before_listening(self):
        script = build_voice_bridge_script(42)
        self.assertIn("/admin/company/jood/voice/42/start", script)
        start_handler = script[script.index("startBtn.addEventListener"):]
        self.assertLess(start_handler.index("await speakReply"), start_handler.index("startRecognition()"))

    def test_bridge_uses_server_tts_hook_not_browser_voice(self):
        script = build_voice_bridge_script(7)
        self.assertIn("window.JoodServerSpeak", script)
        self.assertNotIn("speechSynthesis.speak", script)
        self.assertNotIn("Zariyah غير متوفرة داخل Web Speech", script)

    def test_initial_opening_matches_contact_type(self):
        merchant = initial_voice_opening("merchant")
        customer = initial_voice_opening("customer")
        self.assertIn("جود", merchant)
        self.assertIn("بكجات", merchant)
        self.assertIn("تعاون", merchant)
        self.assertIn("جود", customer)
        self.assertIn("بكجات", customer)
        self.assertNotEqual(merchant, customer)


if __name__ == "__main__":
    unittest.main()
