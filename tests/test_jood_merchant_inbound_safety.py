import unittest

from app.jood_identity import should_jood_ai_reply
from app.jood_policy import sanitize_jood_reply


class MerchantInboundSafetyTests(unittest.TestCase):
    def test_strong_business_auto_reply_is_not_routed_to_jood(self):
        dermo = (
            "شكرا لك على تواصلك مع Dermo Bright. "
            "يرجى إخبارنا بما يمكننا القيام به لمساعدتك."
        )
        english = "Thank you for contacting Example Clinic. We have received your message."

        self.assertFalse(should_jood_ai_reply(dermo, "966575606000"))
        self.assertFalse(should_jood_ai_reply(english, "966575606001"))

        # Short greetings and campaign choices can be genuine human replies.
        self.assertTrue(should_jood_ai_reply("حياك الله", "966575606002"))
        self.assertTrue(should_jood_ai_reply("1", "966575606003"))

    def test_markdown_bold_pakgat_root_url_survives_sanitizer_exactly(self):
        message = "*معكم جود من منصة بكجات — https://pakgat.com*"
        safe = sanitize_jood_reply(
            message,
            approved_urls={"https://pakgat.com"},
        )

        self.assertEqual(safe, message)
        self.assertNotIn("https://pakgat.com/ar", safe)


if __name__ == "__main__":
    unittest.main()
