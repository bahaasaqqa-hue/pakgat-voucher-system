import unittest

from types import SimpleNamespace

from app.jood_outbound import (
    build_contact_outreach_context,
    ensure_outbound_opening,
    outbound_intent_for,
    outbound_instruction_context,
)
from app.jood_catalog import CatalogItem, strict_product_message


class JoodOutboundTests(unittest.TestCase):
    def test_customer_outbound_uses_sales_intent(self):
        self.assertEqual(outbound_intent_for("customer"), "customer_sales")

    def test_merchant_outbound_uses_prospecting_intent(self):
        self.assertEqual(outbound_intent_for("merchant"), "merchant_prospecting")

    def test_outbound_context_marks_manager_goal_as_internal_not_customer_history(self):
        context = outbound_instruction_context("merchant", "عرّفيهم ببكجات واطلبي اهتمامهم بالشراكة")
        self.assertIn("internal outbound", context.lower())
        self.assertIn("not a customer utterance", context.lower())
        self.assertIn("عرّفيهم ببكجات", context)

    def test_contact_context_personalizes_without_changing_the_instruction(self):
        contact = SimpleNamespace(
            display_name="سارة",
            business_name="مركز سارة",
            city="الرياض",
            notes="مهتمة بعروض العناية",
        )
        context = build_contact_outreach_context(contact, "التوجيه العام")
        self.assertIn("التوجيه العام", context)
        self.assertIn("سارة", context)
        self.assertIn("مركز سارة", context)
        self.assertIn("الرياض", context)
        self.assertNotIn("Company AI mode", context)

    def test_generic_customer_service_reply_is_replaced_with_outbound_opening(self):
        contact = SimpleNamespace(display_name="بهاء", business_name=None)
        result = ensure_outbound_opening(
            "أهلاً بك أستاذ بهاء، أنا جود من منصة باكيجات. كيف أساعدك اليوم؟",
            "customer",
            contact,
        )
        self.assertIn("أتواصل معك", result)
        self.assertIn("عروض", result)
        self.assertNotIn("كيف أساعدك", result)

    def test_clear_merchant_opening_is_preserved_and_gets_official_site(self):
        contact = SimpleNamespace(display_name="سارة", business_name="مركز سارة")
        message = "السلام عليكم أستاذة سارة، معك جود من باكيجات. أتواصل معك لعرض فرصة تعاون مناسبة لمركز سارة، هل يناسبك أرسل التفاصيل؟"
        result = ensure_outbound_opening(message, "merchant", contact)
        self.assertTrue(result.startswith(message))
        self.assertIn("https://pakgat.com/ar", result)
        self.assertEqual(result.count("https://pakgat.com/ar"), 1)

    def test_customer_opening_is_always_the_strict_catalog_template(self):
        contact = SimpleNamespace(display_name="بهاء", business_name=None)
        product = CatalogItem("11", "كوبون غسيل", "https://pakgat.com/ar/p/11", 17.25)
        result = ensure_outbound_opening("نص مبيعات من النموذج", "customer", contact, product)
        self.assertEqual(result, strict_product_message(product))


if __name__ == "__main__":
    unittest.main()
