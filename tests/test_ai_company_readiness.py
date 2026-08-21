import unittest

from app.ai_company_readiness import salla_source_access, summarize_system_statuses


class ReadinessTests(unittest.TestCase):
    def test_products_need_product_read_scope(self):
        self.assertEqual(salla_source_access("Salla Products / Inventory", True, "orders.read")[0], "Needs Integration")
        self.assertEqual(salla_source_access("Salla Products / Inventory", True, "orders.read products.read")[0], "Readable")

    def test_carts_and_reviews_need_separate_scopes(self):
        scope = "products.read abandoned_carts.read"
        self.assertEqual(salla_source_access("Salla Abandoned Carts", True, scope)[0], "Readable")
        self.assertEqual(salla_source_access("Salla Reviews", True, scope)[0], "Needs Integration")

    def test_no_oauth_means_not_ready(self):
        self.assertEqual(salla_source_access("Salla Reviews", False, "reviews.read")[0], "Needs Integration")

    def test_system_completion_is_not_operational_health(self):
        summary = summarize_system_statuses(["يعمل", "يعمل جزئيًا", "هيكل جاهز", "بانتظار الربط", "يعمل"])
        self.assertEqual(summary, {"total": 5, "complete": 2, "partial": 1, "pending": 2})


if __name__ == "__main__":
    unittest.main()
