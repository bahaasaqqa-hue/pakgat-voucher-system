import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import google_search_console as gsc


class SearchConsoleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        gsc.SearchConsoleSnapshot.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_sync_stores_aggregate_queries_and_pages(self):
        def fetcher(_site, dimensions):
            if not dimensions:
                return {"rows": [{"clicks": 42, "impressions": 1200, "ctr": 0.035, "position": 8.4}]}
            key = "كوبونات الرياض" if dimensions == ["query"] else "https://pakgat.com/"
            return {"rows": [{"keys": [key], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 4.2}]}

        row = gsc.sync_snapshot(self.db, "sc-domain:pakgat.com", fetcher=fetcher)

        self.assertEqual(row.clicks, 42)
        self.assertEqual(row.impressions, 1200)
        self.assertAlmostEqual(row.ctr, 0.035)
        self.assertIn("كوبونات الرياض", row.top_queries_json)
        self.assertIn("https://pakgat.com/", row.top_pages_json)
        self.assertEqual(gsc.connection_state(self.db)[0], "Connected")

    def test_empty_report_is_stored_as_real_zeroes(self):
        row = gsc.sync_snapshot(self.db, "sc-domain:pakgat.com", fetcher=lambda *_: {"rows": []})
        self.assertEqual((row.clicks, row.impressions, row.ctr, row.position), (0, 0, 0.0, 0.0))

    def test_page_labels_do_not_render_raw_urls_that_merge_with_metrics(self):
        self.assertEqual(gsc.display_page_label("https://pakgat.com/"), "الصفحة الرئيسية")
        self.assertEqual(gsc.display_page_label("https://pakgat.com/ar"), "الصفحة العربية")
        self.assertEqual(gsc.display_page_label("https://pakgat.com/en/"), "الصفحة الإنجليزية")
        label = gsc.display_page_label("https://pakgat.com/%D8%A7%D9%84%D9%87%D8%AF%D8%A7%D9%8A%D8%A7/c2865369")
        self.assertTrue(label.startswith("مسار: /الهدايا/"))
        self.assertNotIn("https://", label)


if __name__ == "__main__":
    unittest.main()
