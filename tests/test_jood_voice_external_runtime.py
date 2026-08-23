import unittest
from unittest.mock import patch

from app import jood_voice_live_bridge as live
from app import jood_voice_self_test_standalone as standalone


class JoodVoiceExternalRuntimeTests(unittest.TestCase):
    def test_standalone_page_loads_same_origin_external_script(self):
        with patch.object(standalone.core, "require_admin", return_value=None):
            response = standalone.jood_voice_self_test_standalone(9, object())

        html = bytes(response.body).decode("utf-8")
        self.assertIn(
            'src="/admin/company/jood/voice/9/self-test.js"',
            html,
        )
        self.assertNotIn("btn.addEventListener", html)

    def test_standalone_runtime_posts_to_tts(self):
        script = standalone.build_standalone_self_test_script(9)

        self.assertIn("/admin/company/jood/voice/9/tts", script)
        self.assertIn("btn.addEventListener('click'", script)
        self.assertIn("method: 'POST'", script)
        self.assertIn("audio.play()", script)

    def test_live_runtime_is_served_as_javascript(self):
        with patch.object(live, "_require_admin_api", return_value=None):
            response = live.jood_voice_runtime_script(12, object())

        script = bytes(response.body).decode("utf-8")
        self.assertIn("/admin/company/jood/voice/12/start", script)
        self.assertIn("/admin/company/jood/voice/12/tts", script)
        self.assertIn("startBtn.addEventListener('click'", script)
        self.assertTrue(response.media_type.startswith("application/javascript"))

    def test_external_runtime_routes_are_registered(self):
        paths = {getattr(route, "path", "") for route in live.core.app.routes}

        self.assertIn(
            "/admin/company/jood/voice/{session_id}/runtime.js",
            paths,
        )
        self.assertIn(
            "/admin/company/jood/voice/{session_id}/self-test.js",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
