import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import application as core


class MerchantProfileAdminTests(unittest.TestCase):
    def test_profile_admin_extension_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_profile_admin"))

    def test_profile_edit_route_is_registered(self):
        import app.merchant_profile_admin  # noqa: F401
        paths = {getattr(route, "path", "") for route in core.app.routes}
        self.assertIn("/admin/merchants/{merchant_id}/edit", paths)


if __name__ == "__main__":
    unittest.main()
