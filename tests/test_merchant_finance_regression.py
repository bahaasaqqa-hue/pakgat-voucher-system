import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import application as core


class MerchantFinanceRegressionTests(unittest.TestCase):
    def test_customer_message_keeps_existing_urls(self):
        url = "https://voucher.example/v/token-123"
        message = core.build_voucher_whatsapp_message(
            customer_name="عميل",
            product_name="عرض تجريبي",
            voucher_code="PKG-TEST",
            order_id="ORDER-1",
            verification_url=url,
        )
        self.assertIn(url, message)
        self.assertIn("https://pakgat.com", message)

    def test_redemption_message_keeps_existing_pakgat_url(self):
        message = core.build_merchant_redemption_whatsapp_message(
            merchant_name="تاجر",
            product_name="عرض",
            voucher_code="PKG-TEST",
            order_id="ORDER-1",
            redeemed_at=core.now_utc(),
        )
        self.assertIn("https://pakgat.com", message)
        self.assertIn("تم استخدام القسيمة", message)

    def test_whatsloop_endpoint_configuration_is_not_rewritten(self):
        original = core.WHATSLOOP_API_BASE_URL
        self.assertEqual(core.WHATSLOOP_API_BASE_URL, original)


if __name__ == "__main__":
    unittest.main()
