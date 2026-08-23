import importlib
import importlib.util
from pathlib import Path
import unittest

import main
from app.jood_voice_live_bridge import build_live_voice_bridge_script


BRIDGE_PATH = "/admin/company/jood/voice/{session_id}/bridge"
SELF_TEST_PATH = "/admin/company/jood/voice/{session_id}/self-test"


class JoodVoiceRouteArchitectureTests(unittest.TestCase):
    def test_bridge_get_route_has_one_canonical_owner(self):
        routes = [
            route
            for route in main.app.routes
            if getattr(route, "path", "") == BRIDGE_PATH
            and "GET" in (getattr(route, "methods", set()) or set())
        ]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].endpoint.__module__, "app.jood_voice_bridge_ui")
        self.assertEqual(routes[0].dependant.call.__module__, "app.jood_voice_bridge_ui")

    def test_main_does_not_import_deprecated_bridge_patch_modules(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertNotIn("jood_voice_local_self_test", source)
        self.assertNotIn("jood_voice_self_test_inline", source)
        self.assertIn("jood_voice_self_test_page", source)

    def test_live_call_script_has_no_embedded_self_test_button_or_listener(self):
        script = build_live_voice_bridge_script(7)
        self.assertNotIn("testVoiceBtn", script)
        self.assertNotIn("test-jood-voice", script)
        self.assertNotIn("اختبار صوت جود", script)
        self.assertIn("startBtn.addEventListener", script)
        self.assertIn("MediaRecorder", script)

    def test_standalone_self_test_page_is_registered_and_isolated(self):
        spec = importlib.util.find_spec("app.jood_voice_self_test_page")
        self.assertIsNotNone(spec)
        module = importlib.import_module("app.jood_voice_self_test_page")
        script = module.build_self_test_script(7)

        self.assertIn("/admin/company/jood/voice/7/tts", script)
        self.assertIn("navigator.mediaDevices.enumerateDevices", script)
        self.assertIn("audiooutput", script)
        self.assertIn("setSinkId", script)
        self.assertIn("realtek", script.lower())
        self.assertIn("speakers", script.lower())
        self.assertIn("voicemeeter", script.lower())
        self.assertIn("motorola", script.lower())
        self.assertIn("TTS HTTP", script)
        self.assertIn("Audio Bytes", script)
        self.assertIn("Selected Sink", script)
        self.assertIn("Audio Decode", script)
        self.assertIn("Playback State", script)
        self.assertNotIn("MediaRecorder", script)
        self.assertNotIn("/stt", script.lower())
        self.assertNotIn("startCaptureLoop", script)

        paths = {getattr(route, "path", "") for route in main.app.routes}
        self.assertIn(SELF_TEST_PATH, paths)


if __name__ == "__main__":
    unittest.main()
