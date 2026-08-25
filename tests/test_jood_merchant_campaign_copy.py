import unittest
from types import SimpleNamespace

from app import jood_whatsapp_campaign as campaign_module


EXPECTED_MESSAGE = """*مساكم الله بالخير ✨*

*معكم جود من منصة بكجات — https://pakgat.com*

أعجبنا نشاط *صالون نجلا*، ونشوف عندكم فرصة ممتازة لـ *استقطاب عملاء جدد في الرياض* من خلال *كوبونات وعروض وبكجات مميزة*.

*بكجات منصة متخصصة في مدينة الرياض*، ونعمل على ربط الأنشطة المميزة بعملاء يبحثون عن عروض وتجارب تستحق التجربة.

التعاون معنا *بدون أي تكاليف مسبقة عليكم*، ونساعدكم في تجهيز العرض وإبرازه بشكل واضح وجذاب.

إذا ناسبكم نبدأ، ردوا برقم واحد فقط:

*1 — أرسلوا التفاصيل*
*2 — لدي استفسار*"""


class ApprovedMerchantCampaignCopyTests(unittest.TestCase):
    def test_merchant_campaign_uses_approved_copy_verbatim(self):
        builder = getattr(campaign_module, "approved_merchant_campaign_message", None)
        self.assertTrue(callable(builder), "approved_merchant_campaign_message must exist")
        contact = SimpleNamespace(
            display_name="صالون نجلا",
            business_name="سبا وتجميل",
            phone="966594116669",
        )
        self.assertEqual(builder(contact), EXPECTED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
