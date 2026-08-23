import unittest

from app import jood_voice_server_tts as tts


class _FakeCommunicator:
    def __init__(self, text, voice, **kwargs):
        self.text = text
        self.voice = voice
        self.kwargs = kwargs

    async def stream(self):
        yield {"type": "WordBoundary", "data": b"ignored"}
        yield {"type": "audio", "data": b"abc"}
        yield {"type": "audio", "data": b"def"}


class JoodVoiceServerTTSTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesizer_uses_zariyah_and_returns_audio(self):
        seen = {}

        def factory(text, voice, **kwargs):
            seen.update(text=text, voice=voice, kwargs=kwargs)
            return _FakeCommunicator(text, voice, **kwargs)

        audio = await tts.synthesize_zariyah_mp3("مرحبا من جود", communicator_factory=factory)
        self.assertEqual(audio, b"abcdef")
        self.assertEqual(seen["voice"], "ar-SA-ZariyahNeural")
        self.assertEqual(seen["kwargs"]["rate"], "-2%")

    async def test_empty_tts_text_is_rejected(self):
        with self.assertRaises(ValueError):
            await tts.synthesize_zariyah_mp3("   ", communicator_factory=_FakeCommunicator)

    def test_overlay_uses_server_tts_and_browser_audio_context(self):
        script = tts.build_server_tts_overlay(17)
        self.assertIn("/admin/company/jood/voice/17/tts", script)
        self.assertIn("AudioContext", script)
        self.assertIn("arrayBuffer", script)
        self.assertIn("decodeAudioData", script)
        self.assertNotIn("SpeechSynthesisUtterance", script)

    def test_tts_route_is_registered(self):
        paths = {getattr(route, "path", "") for route in tts.core.app.routes}
        self.assertIn("/admin/company/jood/voice/{session_id}/tts", paths)


if __name__ == "__main__":
    unittest.main()
