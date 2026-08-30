import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


class MerchantContractStorageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_merchant_contract_has_agreement_number_column(self):
        self.assertIn("agreement_number", finance.MerchantContract.__table__.c)

    def test_delivery_model_is_registered(self):
        self.assertTrue(hasattr(finance, "MerchantContractDelivery"))

    def test_agreement_number_generator_is_available(self):
        self.assertTrue(callable(getattr(finance, "next_agreement_number", None)))

    def test_agreement_number_format_uses_riyadh_year_month(self):
        generator = getattr(finance, "next_agreement_number", None)
        self.assertTrue(callable(generator))
        number = generator(
            self.db,
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.assertRegex(number, r"^PKG-MA-2026-08-\d{4}$")


if __name__ == "__main__":
    unittest.main()
