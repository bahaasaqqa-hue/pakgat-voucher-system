import os
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.ai_company_dashboard_v2 import analytics_overview_rows


class CompanyAnalyticsOverviewTests(unittest.TestCase):
    def test_overview_exposes_real_connected_metrics(self):
        rows = analytics_overview_rows({
            "orders": 8,
            "confirmed_orders": 4,
            "pending_orders": 4,
            "revenue": 1250.0,
            "aov": 312.5,
            "confirmed_units": 9,
            "products_sold": 3,
            "ga_sessions": 744,
            "ga_users": 337,
            "ga_page_views": 2410,
            "ga_key_events": 7,
            "vouchers_total": 2,
            "vouchers_redeemed": 1,
            "notifications_sent": 2,
            "notifications_failed": 0,
            "delivery_confirmed": 1,
            "help_requests": 1,
        })

        rendered = " ".join(value for _, value, _ in rows)
        for value in ("8", "4", "1,250.00 SAR", "312.50 SAR", "744", "2,410", "50.0%", "1"):
            self.assertIn(value, rendered)
        self.assertNotIn("بيانات جزئية متاحة", rendered)

    def test_overview_keeps_unavailable_metrics_honest(self):
        rows = analytics_overview_rows({"ga_sessions": None})
        rendered = " ".join(value for _, value, _ in rows)
        self.assertIn("بانتظار أول قراءة GA4", rendered)
        self.assertIn("0.0% من الطلبات المؤكدة", rendered)

    def test_company_copy_no_longer_claims_connected_sources_are_waiting(self):
        source = Path("app/ai_company_dashboard_v2.py").read_text(encoding="utf-8")
        self.assertNotIn("Google ينتظر الربط", source)
        self.assertNotIn("Search Console وGA4 غير مربوطين بعد", source)
        self.assertNotIn("القراءة الكاملة تنتظر Salla OAuth", source)


if __name__ == "__main__":
    unittest.main()
