import unittest

from app.jood_policy import (
    CAR_CARE_URL,
    PAKGAT_HOME_URL,
    approved_url_for_intent,
    sanitize_jood_reply,
)


class JoodPolicyTests(unittest.TestCase):
    def test_legacy_car_care_url_is_replaced_with_canonical_url(self):
        text = "العروض هنا https://pakgat.com/ar/categories/car-care"
        self.assertEqual(sanitize_jood_reply(text), f"العروض هنا {CAR_CARE_URL}")
        self.assertNotIn("/ar/categories/car-care", sanitize_jood_reply(text))

    def test_relative_legacy_car_care_path_is_replaced(self):
        text = "استخدم /ar/categories/car-care"
        self.assertEqual(sanitize_jood_reply(text), f"استخدم {CAR_CARE_URL}")

    def test_unknown_url_is_replaced_with_home(self):
        text = "شوف https://example.com/fake-offer"
        self.assertEqual(sanitize_jood_reply(text), f"شوف {PAKGAT_HOME_URL}")

    def test_approved_urls_survive(self):
        self.assertEqual(sanitize_jood_reply(CAR_CARE_URL), CAR_CARE_URL)
        self.assertEqual(sanitize_jood_reply(PAKGAT_HOME_URL), PAKGAT_HOME_URL)

    def test_car_care_intent_returns_only_canonical_url(self):
        self.assertEqual(approved_url_for_intent("car_care"), CAR_CARE_URL)
        self.assertIsNone(approved_url_for_intent("unknown"))

    def test_car_care_question_forces_canonical_url_into_reply(self):
        reply = sanitize_jood_reply(
            "أكيد، عندنا قسم للعناية بالسيارات.",
            customer_text="ابغى عروض العناية بالسيارات",
        )
        self.assertIn(CAR_CARE_URL, reply)
        self.assertNotIn("/ar/categories/car-care", reply)

    def test_non_car_care_question_does_not_append_car_care_url(self):
        reply = sanitize_jood_reply("حياك الله.", customer_text="مرحبا")
        self.assertNotIn(CAR_CARE_URL, reply)

    def test_completed_handoff_claim_is_softened_without_real_handoff(self):
        text = "تم رفع بياناتكم لفريق الشراكات وسيتواصل معكم الفريق."
        safe = sanitize_jood_reply(text, allow_handoff_claim=False)
        self.assertNotIn("تم رفع بياناتكم", safe)
        self.assertIn("أقدر أرفع بياناتكم", safe)

    def test_completed_handoff_claim_is_allowed_after_real_handoff(self):
        text = "تم رفع بياناتكم لفريق الشراكات."
        self.assertEqual(sanitize_jood_reply(text, allow_handoff_claim=True), text)


if __name__ == "__main__":
    unittest.main()
