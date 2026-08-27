import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


class MerchantVoucherPageTests(unittest.TestCase):
    def test_voucher_page_extension_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_voucher_page"))

    def test_partner_details_card_contains_operational_information(self):
        from app import merchant_voucher_page as page

        html = page.partner_details_html(
            partner_name="صالون الاختبار",
            hours="10 ص - 10 م",
            contact="0500000000",
            address="حي العليا، الرياض",
            map_url="https://maps.google.com/example",
        )
        self.assertIn("تفاصيل مقدم الخدمة", html)
        self.assertIn("10 ص - 10 م", html)
        self.assertIn("0500000000", html)
        self.assertIn("حي العليا، الرياض", html)
        self.assertIn("https://maps.google.com/example", html)


if __name__ == "__main__":
    unittest.main()
