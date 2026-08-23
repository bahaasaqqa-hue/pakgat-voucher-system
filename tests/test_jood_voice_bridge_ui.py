import importlib.util
import unittest

from app.jood_voice_live_bridge import build_live_voice_bridge_script, initial_voice_opening


class JoodVoiceBridgeUITests(unittest.TestCase):
    def test_bridge_captures_voicemeeter_b1_with_media_recorder_not_speech_recognition(self):
        script = build_live_voice_bridge_script(42)
        self.assertIn("navigator.mediaDevices.enumerateDevices", script)
        self.assertIn("Voicemeeter", script)
        self.assertIn("B1", script)
        self.assertIn("MediaRecorder", script)
        self.assertIn("/admin/company/jood/voice/42/stt", script)
        self.assertNotIn("SpeechRecognition", script)
        self.assertNotIn("recognition.start", script)

    def test_bridge_has_visible_audio_diagnostics(self):
        script = build_live_voice_bridge_script(42)
        self.assertIn("setDiagnostic('b1'", script)
        self.assertIn("setDiagnostic('signal'", script)
        self.assertIn("setDiagnostic('stt'", script)
        self.assertIn("setDiagnostic('tts'", script)
        self.assertIn("runDiagnostics", script)

    def test_bridge_reports_phone_link_signal_failure_in_plain_arabic(self):
        script = build_live_voice_bridge_script(42)
        self.assertIn("صوت المكالمة لا يصل من Phone Link إلى مدخل جود", script)

    def test_bridge_speaks_opening_before_capture_loop(self):
        script = build_live_voice_bridge_script(42)
        self.assertIn("/admin/company/jood/voice/42/start", script)
        start_handler = script[script.index("startBtn.addEventListener"):]
        self.assertLess(start_handler.index("await speakReply"), start_handler.index("startCaptureLoop()"))

    def test_bridge_uses_server_tts_not_browser_speech_synthesis(self):
        script = build_live_voice_bridge_script(7)
        self.assertIn("/admin/company/jood/voice/7/tts", script)
        self.assertIn("AudioContext", script)
        self.assertNotIn("speechSynthesis.speak", script)
        self.assertNotIn("SpeechSynthesisUtterance", script)

    def test_bridge_is_chrome_first_and_has_visible_running_state(self):
        script = build_live_voice_bridge_script(7)
        self.assertIn("Chrome", script)
        self.assertIn("startBtn.textContent = 'جود تعمل الآن'", script)
        self.assertIn("startBtn.textContent = 'إعادة تشغيل جود'", script)
        self.assertNotIn("Microsoft Edge", script)

    def test_server_stt_module_is_present(self):
        self.assertIsNotNone(importlib.util.find_spec("app.jood_voice_server_stt"))

    def test_initial_opening_matches_contact_type(self):
        merchant = initial_voice_opening("merchant")
        customer = initial_voice_opening("customer")
        self.assertIn("جود", merchant)
        self.assertIn("بكجات", merchant)
        self.assertIn("تعاون", merchant)
        self.assertIn("جود", customer)
        self.assertIn("بكجات", customer)
        self.assertNotEqual(merchant, customer)

    def test_voice_start_route_is_registered(self):
        from app.jood_voice_live_bridge import core

        paths = {getattr(route, "path", "") for route in core.app.routes}
        self.assertIn("/admin/company/jood/voice/{session_id}/start", paths)


if __name__ == "__main__":
    unittest.main()
