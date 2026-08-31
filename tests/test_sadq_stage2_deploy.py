import pathlib
import subprocess
import unittest


class SadqStage2DeployTests(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path("deploy/gce/apply_sadq_stage2_signing.sh")
        self.text = self.path.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self):
        result = subprocess.run(["bash", "-n", str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rollout_is_bounded_and_keeps_jood_main_read_only(self):
        self.assertNotIn("set -e", self.text)
        self.assertIn("PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED", self.text)
        self.assertIn('"app/jood_outbound.py"', self.text)
        self.assertIn('"app/whatsloop_inbound.py"', self.text)
        self.assertIn('"main.py"', self.text)
        self.assertNotIn("git merge", self.text)
        self.assertNotIn("git checkout", self.text)

    def test_preflights_pdf_converter_and_fixes_merchant_upload_limit(self):
        converter = self.text.index("SADQ_STAGE2_PDF_CONVERTER_OK")
        mutation = self.text.index("MUTATED=1")
        self.assertLess(converter, mutation)
        self.assertIn("client_max_body_size 50m;", self.text)
        self.assertIn("nginx -t", self.text)
        self.assertIn("MERCHANT_UPLOAD_LIMIT_50M_OK", self.text)

    def test_rollout_runs_only_targeted_stage2_tests_before_restart(self):
        self.assertIn("test_merchant_contract_pdf.py", self.text)
        self.assertIn("test_sadq_signing_client.py", self.text)
        self.assertIn("test_merchant_onboarding_sadq_start.py", self.text)
        tests_ok = self.text.index("SADQ_STAGE2_TARGETED_TESTS_OK")
        restart = self.text.index("systemctl restart pakgat-voucher", tests_ok)
        self.assertLess(tests_ok, restart)

    def test_rollout_executes_the_staged_tests_not_the_production_test_directory(self):
        self.assertIn('"$PY" "$STAGE/tests/test_merchant_contract_pdf.py" -v', self.text)
        self.assertIn('"$PY" "$STAGE/tests/test_sadq_signing_client.py" -v', self.text)
        self.assertIn('"$PY" "$STAGE/tests/test_merchant_onboarding_sadq_start.py" -v', self.text)
        self.assertNotIn("-m unittest discover -s tests", self.text)


if __name__ == "__main__":
    unittest.main()
