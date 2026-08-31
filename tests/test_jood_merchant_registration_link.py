import unittest

from app.jood_whatsapp_context import (
    MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY,
    JoodWhatsAppContext,
    merchant_campaign_choice_action,
)


MERCHANT_REGISTER_URL = "https://merchant.pakgat.com/merchant/register"


class MerchantRegistrationLinkTests(unittest.TestCase):
    def test_send_details_reply_contains_registration_link_only_for_choice_one(self):
        context = JoodWhatsAppContext(
            contact_id=1,
            mode="merchant",
            objective="merchant partnership",
            source="campaign",
            active=True,
            state_json={
                "direction": "outbound",
                "persona": "outbound_merchant_acquisition",
                "status": "active",
            },
        )

        choice_one = merchant_campaign_choice_action("أرسلوا التفاصيل", "merchant", context)
        choice_two = merchant_campaign_choice_action("لدي استفسار", "merchant", context)

        self.assertIsNotNone(choice_one)
        self.assertEqual(choice_one.reply, MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY)
        self.assertIn(MERCHANT_REGISTER_URL, choice_one.reply)
        self.assertIn("التحقق عبر نفاذ", choice_one.reply)

        self.assertIsNotNone(choice_two)
        self.assertEqual(choice_two.reply, "")
        self.assertEqual(choice_two.handoff_details, "merchant_campaign_silent_human_takeover")


if __name__ == "__main__":
    unittest.main()
