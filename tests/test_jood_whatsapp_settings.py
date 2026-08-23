import unittest
from types import SimpleNamespace

from app.jood_whatsapp_settings import (
    CUSTOMER_DEFAULT_OUTREACH_PROMPT,
    MERCHANT_DEFAULT_OUTREACH_PROMPT,
    compose_outreach_instruction,
    default_prompt_for_type,
)


class JoodWhatsAppSettingsTests(unittest.TestCase):
    def test_customer_and_merchant_defaults_are_isolated(self):
        self.assertEqual(default_prompt_for_type("customer"), CUSTOMER_DEFAULT_OUTREACH_PROMPT)
        self.assertEqual(default_prompt_for_type("merchant"), MERCHANT_DEFAULT_OUTREACH_PROMPT)
        self.assertNotEqual(CUSTOMER_DEFAULT_OUTREACH_PROMPT, MERCHANT_DEFAULT_OUTREACH_PROMPT)

    def test_blank_override_uses_stored_default(self):
        self.assertEqual(compose_outreach_instruction("merchant", "توجيه التاجر", ""), "توجيه التاجر")

    def test_override_supplements_default_instead_of_replacing_it(self):
        result = compose_outreach_instruction("customer", "التوجيه العام", "اذكري عرض غسيل السيارة")
        self.assertIn("التوجيه العام", result)
        self.assertIn("اذكري عرض غسيل السيارة", result)
        self.assertLess(result.index("التوجيه العام"), result.index("اذكري عرض غسيل السيارة"))


if __name__ == "__main__":
    unittest.main()
