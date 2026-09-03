import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import application as core


class MerchantBranchTests(unittest.TestCase):
    def test_branch_extension_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_branches"))

    def test_branch_routes_are_registered(self):
        import app.merchant_branches  # noqa: F401
        paths = {getattr(route, "path", "") for route in core.app.routes}
        self.assertIn("/admin/merchants/{merchant_id}/branches", paths)
        self.assertIn("/admin/merchants/{merchant_id}/branches/save", paths)


if __name__ == "__main__":
    unittest.main()
