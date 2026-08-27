import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


class MerchantFinanceModelTests(unittest.TestCase):
    def test_merchant_finance_module_exists(self):
        self.assertIsNotNone(
            importlib.util.find_spec("app.merchant_finance"),
            "merchant_finance module must be added as an isolated extension",
        )


if __name__ == "__main__":
    unittest.main()
