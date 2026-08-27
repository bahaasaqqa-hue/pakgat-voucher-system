import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app import application as core
from app import gce_entry as gce
from app import merchant_finance as finance


class MerchantAdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        gce.LocalPartnerProduct.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _unauthenticated_request(self, path):
        return Request({
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("127.0.0.1", 12345),
        })

    def test_merchant_list_requires_admin_auth(self):
        response = finance.admin_merchants(self._unauthenticated_request("/admin/merchants"), self.db)
        self.assertIsInstance(response, RedirectResponse)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_settlements_requires_admin_auth(self):
        response = finance.admin_settlements(self._unauthenticated_request("/admin/settlements"), self.db)
        self.assertIsInstance(response, RedirectResponse)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_expected_finance_routes_are_registered(self):
        paths = {getattr(route, "path", "") for route in core.app.routes}
        self.assertIn("/admin/merchants", paths)
        self.assertIn("/admin/merchants/{merchant_id}", paths)
        self.assertIn("/admin/settlements", paths)


if __name__ == "__main__":
    unittest.main()
