import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from app import application as core


class MerchantPortalEntryTests(unittest.TestCase):
    def test_merchant_portal_module_exists_and_routes_are_registered(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_portal"))
        import app.merchant_portal  # noqa: F401

        paths = {
            (getattr(route, "path", ""), method)
            for route in core.app.routes
            for method in (getattr(route, "methods", set()) or set())
        }
        self.assertIn(("/merchant", "GET"), paths)
        self.assertIn(("/merchant/login/request", "POST"), paths)
        self.assertIn(("/merchant/login/verify", "POST"), paths)
        self.assertIn(("/merchant/dashboard", "GET"), paths)
        self.assertIn(("/merchant/logout", "POST"), paths)


if __name__ == "__main__":
    unittest.main()
