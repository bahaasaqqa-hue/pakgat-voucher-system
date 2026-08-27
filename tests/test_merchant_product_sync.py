import os
import unittest
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app import gce_entry as gce
from app import merchant_finance as finance
from app import merchant_finance_hooks as hooks


class MerchantProductSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.AuditLog.__table__.create(self.engine)
        gce.LocalPartnerProduct.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)
        merchant = finance.Merchant(code="PKG-M-SYNC", display_name="Sync Merchant")
        self.db.add(merchant)
        self.db.flush()
        self.link = finance.MerchantProductLink(
            merchant_id=merchant.id,
            product_id="12345",
            sku="PKG-QR-SYNC",
            product_name_snapshot="Old Name",
            commission_percent=Decimal("20.00"),
            product_status="active",
        )
        self.db.add(self.link)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_salla_status_event_updates_name_status_and_sync_time_without_commission(self):
        result = hooks._sync_product_event(
            self.db,
            "product.status.updated",
            {
                "id": "12345",
                "name": "New Name",
                "status": {"slug": "out"},
                "ends_at": "2026-09-30T23:59:00+03:00",
            },
        )
        self.assertTrue(result["updated"])
        self.db.refresh(self.link)
        self.assertEqual(self.link.product_name_snapshot, "New Name")
        self.assertEqual(self.link.product_status, "out")
        self.assertIsNotNone(self.link.offer_ends_at)
        self.assertIsNotNone(self.link.last_salla_sync_at)
        self.assertEqual(Decimal(self.link.commission_percent), Decimal("20.00"))

    def test_deleted_product_is_retained_as_history(self):
        hooks._sync_product_event(self.db, "product.deleted", {"id": "12345"})
        self.db.refresh(self.link)
        self.assertEqual(self.link.product_status, "deleted")
        self.assertIsNotNone(finance.get_product_link(self.db, "12345"))


if __name__ == "__main__":
    unittest.main()
