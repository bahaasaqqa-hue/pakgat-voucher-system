import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    def test_mission_control_ui_contains_required_sections(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        for marker in (
            "AI Command Bar",
            "AI Core",
            "Situation Room",
            "Decision Matrix",
            "Opportunity Matrix",
            "Activity Rail",
        ):
            self.assertIn(marker, source)

    def test_compact_dashboard_matches_approved_information_architecture(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        for marker in (
            "mc-executive-summary",
            "Market Watch",
            "Product & Pricing Intelligence",
            "Merchant Hunter",
            "Voucher & WhatsApp",
            "SEO & Catalog Watch",
            "Sourcing Watch",
            "Technology & Systems",
            "mc-department-map",
            "<details class='mc-ai-insights'",
        ):
            self.assertIn(marker, source)

    def test_sidebar_embeds_approved_pakgat_logo(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        self.assertIn("PAKGAT_LOGO_DATA_URI", source)
        self.assertIn("data:image/webp;base64,", source)
        self.assertIn("mc-brand-logo", source)

    def test_production_system_card_does_not_claim_render_is_active(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("<span>Render</span>", source)
        self.assertNotIn("Render</strong>", source)

    def test_mission_control_ui_has_protected_command_endpoint(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        self.assertIn('@core.app.post("/admin/company/command")', source)
        self.assertIn("action='/admin/company/command'", source)
        self.assertIn("_admin_redirect(request)", source)

    def test_mission_control_visual_system_has_required_css_hooks(self):
        source = Path("app/ai_company_mission_control_ui.py").read_text(encoding="utf-8")
        for marker in (
            "@keyframes aiCorePulse",
            ".mc-command-strip",
            ".mc-dashboard-grid",
            ".mc-intel-grid",
            ".mc-ai-insights",
        ):
            self.assertIn(marker, source)

    def test_main_imports_mission_control_before_corporate_bridge(self):
        source = Path("main.py").read_text(encoding="utf-8")
        mission_pos = source.find("ai_company_mission_control_ui")
        corporate_pos = source.find("corporate_ai_bridge")
        self.assertGreaterEqual(mission_pos, 0)
        self.assertGreater(corporate_pos, mission_pos)


if __name__ == "__main__":
    unittest.main()
