import unittest
from datetime import datetime, timedelta, timezone

from app.ai_company_mission_control import (
    approval_weight,
    freshness_label,
    opportunity_attention_score,
    resolve_command,
)


class MissionControlTests(unittest.TestCase):
    def test_command_routes_only_to_allowed_internal_pages(self):
        self.assertEqual(resolve_command("اعرض الفرص")[0], "/admin/company/opportunities")
        self.assertEqual(resolve_command("القرارات والموافقات")[0], "/admin/company/governance")
        self.assertEqual(resolve_command("حالة المصادر")[0], "/admin/company/sources")
        self.assertEqual(resolve_command("شغل الشركة")[0], "RUN_COMPANY")
        self.assertEqual(resolve_command("SEO و Google")[0], "/admin/company/seo")

    def test_unknown_command_is_non_destructive(self):
        target, message = resolve_command("احذف كل شيء")
        self.assertIsNone(target)
        self.assertIn("غير مدعوم", message)

    def test_approval_weight_prioritizes_p0_and_ceo(self):
        self.assertGreater(
            approval_weight("P0", "CEO ONLY"),
            approval_weight("P2", "APPROVAL"),
        )

    def test_approval_age_never_reduces_priority(self):
        now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        new = approval_weight("P1", "APPROVAL", now, now)
        old = approval_weight("P1", "APPROVAL", now - timedelta(days=4), now)
        self.assertGreaterEqual(old, new)

    def test_opportunity_attention_uses_real_score_when_present(self):
        high = opportunity_attention_score(90, "P1", "new")
        low = opportunity_attention_score(20, "P1", "new")
        self.assertGreater(high, low)
        self.assertLessEqual(high, 100)

    def test_opportunity_attention_is_deterministic_without_score(self):
        self.assertGreater(
            opportunity_attention_score(None, "P0", "new"),
            opportunity_attention_score(None, "P3", "review"),
        )

    def test_freshness_label_uses_real_timestamp(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(freshness_label(now - timedelta(minutes=8), now), "منذ 8 د")
        self.assertEqual(freshness_label(None, now), "—")


if __name__ == "__main__":
    unittest.main()
