import unittest
from pathlib import Path


class SadqStage1DeployContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.path = cls.root / "deploy" / "gce" / "configure_sadq_sandbox_stage1.sh"
        cls.source = cls.path.read_text(encoding="utf-8")

    def test_stage1_deploy_is_bounded_and_does_not_use_set_e(self):
        self.assertNotIn("set -e", self.source)
        self.assertIn("app/sadq_client.py", self.source)
        self.assertIn("/etc/pakgat/pakgat.env", self.source)
        self.assertIn("PROTECTED_FILES", self.source)
        for protected in (
            "main.py",
            "app/jood_outbound.py",
            "app/jood_whatsapp_context.py",
            "app/whatsloop_inbound.py",
        ):
            self.assertIn(protected, self.source)

    def test_stage1_configures_dynamic_credentials_without_static_bearer(self):
        for name in (
            "SADQ_CLIENT_ID",
            "SADQ_CLIENT_SECRET",
            "SADQ_USERNAME",
            "SADQ_PASSWORD",
            "SADQ_ACCOUNT_ID",
            "SADQ_ACCOUNT_SECRET",
            "SADQ_WEBHOOK_URL",
            "SADQ_WEBHOOK_TOKEN",
        ):
            self.assertIn(name, self.source)
        self.assertIn("openssl rand -hex 32", self.source)
        self.assertNotIn("SADQ_BEARER_TOKEN=", self.source)

    def test_stage1_verifies_callback_auth_before_registering_webhook(self):
        self.assertIn("PAKGAT_CALLBACK_UNAUTH_PROTECTED", self.source)
        self.assertIn("PAKGAT_CALLBACK_AUTH_VALIDATED", self.source)
        self.assertIn("SADQ_DYNAMIC_AUTH_OK", self.source)
        self.assertIn("SADQ_WEBHOOK_REGISTERED_OK", self.source)
        self.assertLess(
            self.source.index("PAKGAT_CALLBACK_AUTH_VALIDATED"),
            self.source.index("SADQ_WEBHOOK_REGISTERED_OK"),
        )

    def test_stage1_does_not_embed_real_sadq_credentials(self):
        forbidden = (
            "baha@tcapital.sa",
            "398e0909-3247-4ce0-8ba6-5fe0ee7b0be0",
            "TOhIF5IXLfS7YnSL14lgv7UJCVLNztdE",
            "rk&15b!uycGR",
            "dvncxzvcdsshbbzavrwidsbdvdgfdhsbcvbdgf",
        )
        for value in forbidden:
            self.assertNotIn(value, self.source)


if __name__ == "__main__":
    unittest.main()
