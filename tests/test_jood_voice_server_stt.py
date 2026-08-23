import base64
import importlib
import importlib.util
import unittest


class JoodVoiceServerSTTTests(unittest.TestCase):
    def _module(self):
        spec = importlib.util.find_spec("app.jood_voice_server_stt")
        self.assertIsNotNone(spec, "server STT module must exist")
        return importlib.import_module("app.jood_voice_server_stt")

    def test_vertex_payload_contains_inline_webm_audio_and_transcription_prompt(self):
        stt = self._module()
        payload = stt.build_stt_payload(b"\x00\x01\x02", "audio/webm")
        parts = payload["contents"][0]["parts"]
        self.assertIn("Transcribe", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "audio/webm")
        self.assertEqual(parts[1]["inlineData"]["data"], base64.b64encode(b"\x00\x01\x02").decode("ascii"))
        self.assertEqual(payload["generationConfig"]["temperature"], 0)

    def test_no_speech_marker_normalizes_to_empty_transcript(self):
        stt = self._module()
        self.assertEqual(stt.normalize_transcript("<NO_SPEECH>"), "")
        self.assertEqual(stt.normalize_transcript("  مرحبا بك  "), "مرحبا بك")

    def test_stt_route_is_registered(self):
        stt = self._module()
        paths = {getattr(route, "path", "") for route in stt.core.app.routes}
        self.assertIn("/admin/company/jood/voice/{session_id}/stt", paths)


if __name__ == "__main__":
    unittest.main()
