import importlib.util
import unittest

from app import jood_voice_live_bridge as live
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

    def test_visible_bridge_replaces_dead_listen_button_with_one_start_control_and_diagnostics(self):
        self.assertTrue(hasattr(live, "decorate_live_bridge_html"))
        source = """
        <div id='voice-status' class='alert' style='margin-top:14px'>جارٍ فحص Zariyah...</div>
        ابدأ الاتصال يدويًا من Phone Link، ثم اضغط «ابدأ استماع جود». Edge يجب أن يأخذ صوت الطرف الآخر من Voicemeeter، ويخرج صوته إلى AUX → B2.
        <button id='start-listening' class='btn btn-blue' type='button'>ابدأ استماع جود</button>
        <button id='stop-listening' class='btn btn-muted' type='button'>إيقاف</button>
        Voice target: ar-SA-ZariyahNeural. لن يستخدم الجسر صوتًا آخر بصمت إذا لم تكن Zariyah متاحة داخل Edge Web Speech.
        """
        rendered = live.decorate_live_bridge_html(source)
        self.assertIn("id='start-jood'", rendered)
        self.assertIn("تشغيل جود", rendered)
        self.assertIn("diagnostic-browser", rendered)
        self.assertIn("diagnostic-signal", rendered)
        self.assertIn("diagnostic-stt", rendered)
        self.assertIn("diagnostic-tts", rendered)
        self.assertNotIn("ابدأ استماع جود", rendered)
        self.assertNotIn("Edge Web Speech", rendered)

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
        paths = {getattr(route, "path", "") for route in live.core.app.routes}
        self.assertIn("/admin/company/jood/voice/{session_id}/start", paths)


if __name__ == "__main__":
    unittest.main()
