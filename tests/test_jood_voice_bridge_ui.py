import unittest

from app.jood_voice_bridge_ui import build_voice_bridge_script


class JoodVoiceBridgeUITests(unittest.TestCase):
    def test_bridge_targets_saudi_zariyah_and_half_duplex(self):
        script = build_voice_bridge_script(42)
        self.assertIn("ar-SA", script)
        self.assertIn("Zariyah", script)
        self.assertIn("recognition.stop()", script)
        self.assertIn("speechSynthesis.speak", script)
        self.assertIn("/admin/company/jood/voice/42/turn", script)

    def test_bridge_does_not_silently_claim_zariyah_when_missing(self):
        script = build_voice_bridge_script(7)
        self.assertIn("Zariyah غير متوفرة", script)
        self.assertIn("voiceIsZariyah", script)


if __name__ == "__main__":
    unittest.main()
