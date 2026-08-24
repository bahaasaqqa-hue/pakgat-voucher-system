import os
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core


class GoogleAnalyticsTests(unittest.TestCase):
    def setUp(self):
        from app import google_analytics as ga

        self.ga = ga
        self.engine = create_engine("sqlite:///:memory:")
        ga.GoogleAnalyticsSnapshot.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _report():
        return {
            "metricHeaders": [
                {"name": "activeUsers", "type": "TYPE_INTEGER"},
                {"name": "sessions", "type": "TYPE_INTEGER"},
                {"name": "screenPageViews", "type": "TYPE_INTEGER"},
                {"name": "keyEvents", "type": "TYPE_FLOAT"},
            ],
            "rows": [{"metricValues": [
                {"value": "310"},
                {"value": "402"},
                {"value": "1100"},
                {"value": "7.0"},
            ]}],
            "metadata": {"currencyCode": "SAR", "timeZone": "Asia/Riyadh"},
        }

    def test_successful_real_report_is_stored_and_marks_source_connected(self):
        snapshot = self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: self._report(),
        )

        self.assertEqual(snapshot.property_id, "123456789")
        self.assertEqual(snapshot.active_users, 310)
        self.assertEqual(snapshot.sessions, 402)
        self.assertEqual(snapshot.page_views, 1100)
        self.assertEqual(snapshot.key_events, 7)
        self.assertEqual(self.ga.google_analytics_connection_state(self.db, "123456789")[0], "Connected")

    def test_missing_property_never_claims_connected_even_if_an_old_snapshot_exists(self):
        self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: self._report(),
        )

        status, detail = self.ga.google_analytics_connection_state(self.db, "")

        self.assertEqual(status, "Needs Integration")
        self.assertIn("Property ID", detail)

    def test_failed_sync_does_not_create_a_snapshot_or_claim_connected(self):
        def fail(_property_id):
            raise PermissionError("credential details must not leak")

        with self.assertRaises(self.ga.GoogleAnalyticsSyncError) as caught:
            self.ga.sync_ga4_snapshot(self.db, "123456789", fetch_report=fail)

        self.assertEqual(str(caught.exception), "GoogleAnalyticsPermissionError")
        self.assertIsNone(self.db.scalar(select(self.ga.GoogleAnalyticsSnapshot)))
        self.assertEqual(
            self.ga.google_analytics_connection_state(self.db, "123456789")[0],
            "Needs Integration",
        )

    def test_report_without_rows_is_saved_as_real_zeroes(self):
        snapshot = self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: {
                "metricHeaders": [
                    {"name": "activeUsers"},
                    {"name": "sessions"},
                    {"name": "screenPageViews"},
                    {"name": "keyEvents"},
                ],
                "rows": [],
            },
        )

        self.assertEqual(snapshot.active_users, 0)
        self.assertEqual(snapshot.sessions, 0)
        self.assertEqual(snapshot.page_views, 0)
        self.assertEqual(snapshot.key_events, 0)

    def test_fresh_snapshot_is_reused_without_another_provider_call(self):
        first = self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: self._report(),
        )

        def must_not_run(_property_id):
            raise AssertionError("fresh GA4 snapshot should be reused")

        second = self.ga.refresh_ga4_if_stale(
            self.db,
            "123456789",
            fetch_report=must_not_run,
            max_age=timedelta(minutes=15),
        )

        self.assertEqual(second.id, first.id)

    def test_source_inventory_marks_ga_connected_only_after_successful_read(self):
        from app import ai_company_sources

        ai_company_sources.CompanySourceStatus.__table__.create(self.engine)
        core.SallaOAuthCredential.__table__.create(self.engine)
        self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: self._report(),
        )

        with patch.object(self.ga, "GA4_PROPERTY_ID", "123456789"):
            ai_company_sources.refresh_source_inventory(self.db)

        row = self.db.scalar(
            select(ai_company_sources.CompanySourceStatus).where(
                ai_company_sources.CompanySourceStatus.source == "Google Analytics"
            )
        )
        self.assertEqual(row.status, "Connected")
        self.assertIn("read-only", row.detail)

    def test_dedicated_service_account_uses_keyless_impersonation(self):
        with (
            patch.object(self.ga, "GA4_SERVICE_ACCOUNT", "pakgat-ga4-reader@example.iam.gserviceaccount.com"),
            patch.object(self.ga, "_metadata_access_token", return_value="source-token"),
            patch.object(self.ga, "_impersonated_access_token", return_value="analytics-token") as impersonate,
        ):
            token = self.ga._analytics_access_token()

        self.assertEqual(token, "analytics-token")
        impersonate.assert_called_once_with(
            "pakgat-ga4-reader@example.iam.gserviceaccount.com",
            "source-token",
        )

    def test_connected_dashboard_kpi_shows_sessions_and_real_context(self):
        row = self.ga.sync_ga4_snapshot(
            self.db,
            "123456789",
            fetch_report=lambda property_id: self._report(),
        )

        value, subtitle, waiting = self.ga.ga4_dashboard_kpi(row)

        self.assertEqual(value, "402")
        self.assertEqual(subtitle, "310 مستخدمًا · 1,100 مشاهدة صفحة · GA4 متصل")
        self.assertFalse(waiting)

    def test_unconnected_dashboard_kpi_keeps_honest_waiting_state(self):
        value, subtitle, waiting = self.ga.ga4_dashboard_kpi(None)

        self.assertEqual(value, "بانتظار الربط")
        self.assertEqual(subtitle, "Google Analytics · بدون أرقام تقديرية")
        self.assertTrue(waiting)


if __name__ == "__main__":
    unittest.main()
