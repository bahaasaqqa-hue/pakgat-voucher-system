from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).parents[1]
    / "deploy"
    / "gce"
    / "apply_jood_merchant_human_handoff_and_buttons.sh"
)


class MerchantHumanHandoffDeployContractTests(unittest.TestCase):
    def test_deploy_uses_reply_buttons_not_template_transport(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('/messages/send-buttons', source)
        self.assertIn("TEMPLATE_TRANSPORT_REMAINS", source)
        self.assertIn("! grep -q '/messages/send-template'", source)

    def test_deploy_keeps_connection_configuration_read_only(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('pakgat.env" >', source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("git reset", source)

    def test_deploy_has_automatic_rollback_and_silent_handoff_checks(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("rollback()", source)
        self.assertIn("merchant_handoff_silent", source)
        self.assertIn("SILENT_HANDOFF_TESTS=PASS", source)


if __name__ == "__main__":
    unittest.main()
