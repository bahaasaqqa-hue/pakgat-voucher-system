import importlib.util
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app import gce_entry as gce
from app import merchant_finance as finance


class MerchantSettlementWorkerTests(unittest.TestCase):
    def test_worker_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_settlement_worker"))

    def test_thursday_worker_builds_draft_batch_but_never_marks_it_paid(self):
        from app import merchant_settlement_worker as worker

        engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(engine)
        gce.LocalPartnerProduct.__table__.create(engine)
        for table in finance.FINANCE_TABLES:
            table.create(engine)
        db = Session(engine)
        try:
            merchant = finance.Merchant(code="PKG-M-WORKER", display_name="Worker Merchant")
            db.add(merchant)
            db.flush()
            payable = finance.MerchantPayable(
                voucher_id=999,
                merchant_id=merchant.id,
                gross_amount=Decimal("100.00"),
                commission_percent=Decimal("20.00"),
                commission_amount=Decimal("20.00"),
                merchant_amount=Decimal("80.00"),
                status="pending",
                created_at=datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc),
            )
            db.add(payable)
            db.commit()

            result = worker.prepare_thursday_settlements(
                db,
                as_of=datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(result["created"], 1)
            batch = db.scalar(select(finance.SettlementBatch))
            self.assertIsNotNone(batch)
            self.assertEqual(batch.status, "draft")
            self.assertIsNone(batch.paid_at)
            self.assertIsNone(db.scalar(select(finance.SettlementPayment)))
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
