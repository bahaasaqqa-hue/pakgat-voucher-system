import importlib.util
import json
import unittest
from unittest.mock import patch

from app.jood_company_ops import CompanyContact, JoodCallSession
from app.jood_voice_live_bridge import (
    build_live_voice_bridge_script,
    initial_voice_opening,
    start_voice_conversation,
)

# Regression coverage for audible startup and standalone TTS self-test.


class _FakeVoiceDB:
    def __init__(self, session, contact):
        self.session = session
        self.contact = contact

    def get(self, model, object_id):
        if model is JoodCallSession and object_id == self.session.id:
            return self.session
        if model is CompanyContact and object_id == self.contact.id:
            return self.contact
        return None


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

    def test_bridge_has_standalone_voice_self_test_without_starting_call(self):
        script = build_live_voice_bridge_script(7)
        self.assertIn("test-jood-voice", script)
        self.assertIn("اختبار صوت جود", script)
        self.assertIn("السلام عليكم، معك جود من بكجات.", script)
        handler = script[script.index("testVoiceBtn.addEventListener"):script.index("startBtn.addEventListener")]
        self.assertIn("await speakReply", handler)
        self.assertNotIn("runDiagnostics", handler)
        self.assertNotIn("startCall", handler)

    def test_existing_session_start_still_returns_audible_opening(self):
        session = JoodCallSession(id=9, contact_id=3, status="active", transcript="CUSTOMER: سابق")
        contact = CompanyContact(id=3, phone="966500000000", contact_type="customer", status="active")
        db = _FakeVoiceDB(session, contact)

        with patch("app.jood_voice_live_bridge._require_admin_api", return_value=None):
            response = start_voice_conversation(9, object(), db)

        payload = json.loads(bytes(response.body).decode("utf-8"))
        self.assertTrue(payload["already_started"])
        self.assertIn("جود", payload["reply"])
        self.assertIn("بكجات", payload["reply"])

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
