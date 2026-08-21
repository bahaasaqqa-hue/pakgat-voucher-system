import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Unit tests must never depend on the production systemd environment or database.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import ai_company
from app import application as core
from app import ai_company_agent_reporting as reporting


class AgentReportingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.AuditLog.__table__.create(self.engine)
        ai_company.CompanyOpportunity.__table__.create(self.engine)
        reporting.OpportunityReportLink.__table__.create(self.engine)
        reporting.OpportunityAgentReport.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.now = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)
        self.opportunity = ai_company.CompanyOpportunity(
            priority="P1",
            source="test",
            title="Newest opportunity",
            details="details",
            status="new",
            score=1.0,
            created_at=self.now,
            updated_at=self.now,
        )
        self.db.add(self.opportunity)
        self.db.commit()
        self.db.refresh(self.opportunity)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_raw_token_is_hashed_and_resolves_only_while_valid(self):
        link, raw = reporting.create_report_capability(
            self.db,
            dispatch_id=7,
            opportunity_id=self.opportunity.id,
            agent_id=3,
            now=self.now,
        )
        self.db.commit()
        self.assertNotEqual(link.token_hash, raw)
        self.assertEqual(link.token_hash, reporting.hash_report_token(raw))
        self.assertNotIn(raw, link.token_hash)
        resolved = reporting.resolve_report_capability(self.db, raw, now=self.now + timedelta(days=1))
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, link.id)

        link.revoked_at = self.now + timedelta(days=1)
        self.db.commit()
        self.assertIsNone(reporting.resolve_report_capability(self.db, raw, now=self.now + timedelta(days=1, minutes=1)))

    def test_expired_token_is_rejected(self):
        _link, raw = reporting.create_report_capability(
            self.db, 8, self.opportunity.id, 4, now=self.now
        )
        self.db.commit()
        self.assertIsNone(
            reporting.resolve_report_capability(self.db, raw, now=self.now + timedelta(days=31))
        )

    def test_new_capability_does_not_revoke_previous_until_new_assignment_succeeds(self):
        first, _first_raw = reporting.create_report_capability(
            self.db, 1, self.opportunity.id, 10, now=self.now
        )
        self.db.commit()
        second, _second_raw = reporting.create_report_capability(
            self.db, 2, self.opportunity.id, 11, now=self.now + timedelta(hours=1)
        )
        self.db.commit()
        self.db.refresh(first)
        self.assertIsNone(first.revoked_at)
        self.assertIsNone(second.revoked_at)

        reporting.activate_report_capability(
            self.db, second, now=self.now + timedelta(hours=1, minutes=1)
        )
        self.db.commit()
        self.db.refresh(first)
        self.db.refresh(second)
        self.assertIsNotNone(first.revoked_at)
        self.assertIsNone(second.revoked_at)

    def test_message_gets_report_url_but_storage_copy_redacts_raw_token(self):
        url = reporting.report_url("secret-token")
        message = reporting.append_report_link("رسالة الفرصة", url)
        self.assertIn("https://voucher.pakgat.com/agent/report/secret-token", message)
        self.assertIn("تحديث نتيجة الفرصة", message)
        stored = reporting.redact_report_link_for_storage(message)
        self.assertNotIn("secret-token", stored)
        self.assertNotIn("/agent/report/", stored)
        self.assertIn("رابط التقرير الآمن تم إرساله", stored)

    def test_action_mapping_preserves_follow_up_and_maps_business_stages(self):
        self.assertEqual(reporting.map_agent_action("assigned", "follow_up"), "assigned")
        self.assertEqual(reporting.map_agent_action("assigned", "visited"), "contacted")
        self.assertEqual(reporting.map_agent_action("contacted", "interested"), "replied")
        self.assertEqual(reporting.map_agent_action("replied", "negotiating"), "negotiating")
        self.assertEqual(reporting.map_agent_action("negotiating", "won"), "won")
        with self.assertRaises(ValueError):
            reporting.map_agent_action("assigned", "delete_everything")

    def test_reports_are_append_only_rows(self):
        first = reporting.OpportunityAgentReport(
            opportunity_id=self.opportunity.id,
            dispatch_id=1,
            agent_id=2,
            action="contacted",
            notes="first",
            created_at=self.now,
        )
        second = reporting.OpportunityAgentReport(
            opportunity_id=self.opportunity.id,
            dispatch_id=1,
            agent_id=2,
            action="visited",
            notes="second",
            created_at=self.now + timedelta(hours=1),
        )
        self.db.add_all([first, second])
        self.db.commit()
        rows = self.db.query(reporting.OpportunityAgentReport).order_by(reporting.OpportunityAgentReport.id).all()
        self.assertEqual([r.action for r in rows], ["contacted", "visited"])
        self.assertEqual([r.notes for r in rows], ["first", "second"])

    def test_completed_opportunity_waits_48_hours_then_auto_archives_idempotently(self):
        self.opportunity.status = "won"
        self.opportunity.updated_at = self.now - timedelta(hours=47)
        self.db.commit()
        self.assertEqual(reporting.archive_completed_opportunities(self.db, now=self.now), 0)
        self.db.refresh(self.opportunity)
        self.assertEqual(self.opportunity.status, "won")

        self.opportunity.updated_at = self.now - timedelta(hours=49)
        self.db.commit()
        self.assertEqual(reporting.archive_completed_opportunities(self.db, now=self.now), 1)
        self.db.refresh(self.opportunity)
        self.assertEqual(self.opportunity.status, "archived")
        self.assertEqual(reporting.archive_completed_opportunities(self.db, now=self.now + timedelta(minutes=1)), 0)

    def test_valid_png_is_verified_and_reencoded_as_random_webp(self):
        buf = io.BytesIO()
        Image.new("RGB", (12, 12), (255, 255, 255)).save(buf, format="PNG")
        with tempfile.TemporaryDirectory() as tmp:
            filename, media_type = reporting.store_verified_evidence(
                buf.getvalue(), "image/png", Path(tmp)
            )
            self.assertTrue(filename.endswith(".webp"))
            self.assertEqual(media_type, "image/webp")
            self.assertTrue((Path(tmp) / filename).exists())
            with Image.open(Path(tmp) / filename) as saved:
                self.assertEqual(saved.format, "WEBP")

    def test_invalid_and_oversized_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                reporting.store_verified_evidence(b"not-an-image", "image/png", Path(tmp))
            with self.assertRaises(ValueError):
                reporting.store_verified_evidence(
                    b"x" * (reporting.MAX_EVIDENCE_BYTES + 1), "image/jpeg", Path(tmp)
                )
            with self.assertRaises(ValueError):
                reporting.store_verified_evidence(b"GIF89a", "image/gif", Path(tmp))

    def test_source_integration_guards_assignment_and_page_ordering(self):
        dispatch = Path("app/ai_company_dispatch.py").read_text(encoding="utf-8")
        self.assertIn("create_report_capability", dispatch)
        self.assertIn("append_report_link", dispatch)
        self.assertIn("activate_report_capability", dispatch)
        self.assertIn("redact_report_link_for_storage", dispatch)
        self.assertIn("revoke_report_capability", dispatch)
        self.assertIn('opportunity.status = "assigned"', dispatch)
        self.assertIn("رابطًا آمنًا", dispatch)

        compact = Path("app/ai_company_opportunity_compact.py").read_text(encoding="utf-8")
        self.assertIn("archive_completed_opportunities(db)", compact)
        self.assertIn("CompanyOpportunity.created_at.desc(), ai_company.CompanyOpportunity.id.desc()", compact)
        self.assertIn("CompanyOpportunity.updated_at.desc(), ai_company.CompanyOpportunity.id.desc()", compact)
        self.assertIn("مكتملة مؤخرًا", compact)
        self.assertIn("مسندة إلى:", compact)
        self.assertIn("OpportunityAgentReport", compact)

    def test_routes_and_main_import_order_are_registered(self):
        source = Path("app/ai_company_agent_reporting.py").read_text(encoding="utf-8")
        self.assertIn('@core.app.get("/agent/report/{token}"', source)
        self.assertIn('@core.app.post("/agent/report/{token}"', source)
        self.assertIn('@core.app.get("/admin/company/agent-reports/{report_id}/evidence"', source)
        self.assertIn("core.require_admin(request)", source)
        self.assertIn("Referrer-Policy", source)
        self.assertIn("noindex, nofollow", source)

        main = Path("main.py").read_text(encoding="utf-8")
        dispatch_pos = main.find("ai_company_dispatch")
        reporting_pos = main.find("ai_company_agent_reporting")
        compact_pos = main.find("ai_company_opportunity_compact")
        unified_pos = main.find("admin_unified_theme")
        self.assertGreater(reporting_pos, dispatch_pos)
        self.assertGreater(compact_pos, reporting_pos)
        self.assertGreater(unified_pos, compact_pos)


if __name__ == "__main__":
    unittest.main()
