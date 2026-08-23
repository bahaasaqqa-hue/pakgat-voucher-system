import unittest

from app.jood_outbound import outbound_intent_for, outbound_instruction_context


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


if __name__ == "__main__":
    unittest.main()
