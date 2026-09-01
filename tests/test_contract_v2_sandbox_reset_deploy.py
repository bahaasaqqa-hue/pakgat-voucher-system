from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "gce" / "apply_contract_v2_and_reset_sandbox_envelope.sh"


class ContractV2SandboxResetDeployTests(unittest.TestCase):
    def _source(self):
        return SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rollout_is_bounded_and_hard_gated_to_current_test_contract(self):
        source = self._source()
        self.assertNotIn("set -e", source)
        self.assertIn('EXPECTED_APPLICATION_ID="2"', source)
        self.assertIn('EXPECTED_AGREEMENT="PKG-MA-2026-08-0001"', source)
        self.assertIn('EXPECTED_OLD_DOCUMENT_ID="dae9d097-d7ca-4543-a2be-37f69a295244"', source)
        self.assertIn('EXPECTED_OLD_ENVELOPE_ID="9500c022-af56-4254-bf2c-cc8becba7ba7"', source)
        self.assertIn("CONTRACT_V2_PROD_PDF_PAGES=4", source)

    def test_pdf_gate_happens_before_new_sadq_envelope(self):
        source = self._source()
        page_gate = source.index('if [ "$PDF_PAGES" != "4" ]')
        provider_call = source.index("initiate_base64_pdf")
        self.assertLess(page_gate, provider_call)
        self.assertIn("NEW_INVITATION_CREATED=YES", source)
        self.assertIn("db.commit()", source)

    def test_only_contract_generator_and_v2_assets_are_deployed(self):
        source = self._source()
        for protected in (
            "app/jood_identity.py",
            "app/jood_outbound.py",
            "app/jood_policy.py",
            "app/jood_whatsapp_campaign.py",
            "app/jood_whatsapp_campaign_ui.py",
            "app/jood_whatsapp_context.py",
            "app/whatsloop_inbound.py",
            "main.py",
        ):
            self.assertIn(protected, source)
        self.assertIn("PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED", source)
        self.assertIn("merchant_contract_pdf.py", source)
        self.assertIn("merchant_contract_v2_00.b64", source)
        self.assertIn("merchant_contract_v2_04.b64", source)
        self.assertNotIn("cp \"$STAGE/app/jood", source)
        self.assertNotIn("cp \"$STAGE/app/whatsloop", source)
        self.assertNotIn("cp \"$STAGE/main.py", source)


if __name__ == "__main__":
    unittest.main()
