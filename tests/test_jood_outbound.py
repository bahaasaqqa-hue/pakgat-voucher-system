import unittest

from types import SimpleNamespace

from app.jood_outbound import (
    build_contact_outreach_context,
    outbound_intent_for,
    outbound_instruction_context,
)


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


if __name__ == "__main__":
    unittest.main()
