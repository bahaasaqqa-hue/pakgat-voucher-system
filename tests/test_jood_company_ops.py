import unittest
from types import SimpleNamespace

from app.jood_company_ops import (
    can_contact,
    infer_contact_type,
    route_jood_intent,
    trusted_context_for,
)
from app.jood_policy import CAR_CARE_URL


class JoodCompanyOpsTests(unittest.TestCase):
    def test_infer_merchant_from_business_language(self):
        self.assertEqual(infer_contact_type("أنا تاجر وعندي مطعم وودي نتعاون"), "merchant")
        self.assertEqual(infer_contact_type("نحن مركز سبا ونبغى نعرض خدماتنا"), "merchant")

    def test_unknown_general_inbound_defaults_customer(self):
        self.assertEqual(infer_contact_type("مرحبا"), "customer")
        self.assertEqual(infer_contact_type("ايش تبيعو"), "customer")

    def test_company_contact_type_wins_over_message_guessing(self):
        customer = SimpleNamespace(contact_type="customer", status="active")
        merchant = SimpleNamespace(contact_type="merchant", status="active")
        self.assertTrue(can_contact(customer))
        self.assertEqual(route_jood_intent("عندي مطعم", customer.contact_type), "product_or_category")
        self.assertEqual(route_jood_intent("أبغى أعرف عروضكم", merchant.contact_type), "merchant_prospecting")

    def test_customer_intents_are_bounded(self):
        self.assertEqual(route_jood_intent("القسيمة ما تفتح", "customer"), "order_or_voucher")
        self.assertEqual(route_jood_intent("عندي مشكلة دفع واسترجاع", "customer"), "refund_or_payment")
        self.assertEqual(route_jood_intent("أبغى عروض العناية بالسيارات", "customer"), "product_or_category")
        self.assertEqual(route_jood_intent("أبغى أكلم موظف", "customer"), "human_handoff")

    def test_merchant_intents_are_bounded(self):
        self.assertEqual(route_jood_intent("أرسلوا العقد أو الاتفاقية", "merchant"), "merchant_agreement")
        self.assertEqual(route_jood_intent("اسم مطعمي مذاق الرياض والفرع العليا", "merchant"), "merchant_qualification")
        self.assertEqual(route_jood_intent("كيف نتعاون معكم", "merchant"), "merchant_prospecting")

    def test_car_care_context_contains_only_approved_url(self):
        context = trusted_context_for("ابغى عروض العناية بالسيارات", "customer")
        self.assertIn(CAR_CARE_URL, context)
        self.assertNotIn("/ar/categories/car-care", context)

    def test_voucher_context_uses_verified_flow(self):
        context = trusted_context_for("كيف نظام القسائم عندكم", "customer")
        self.assertIn("QR", context)
        self.assertIn("التاجر", context)
        self.assertNotIn("الإيميل", context)

    def test_do_not_contact_blocks_outbound(self):
        active = SimpleNamespace(status="active")
        blocked = SimpleNamespace(status="do_not_contact")
        self.assertTrue(can_contact(active))
        self.assertFalse(can_contact(blocked))


if __name__ == "__main__":
    unittest.main()
