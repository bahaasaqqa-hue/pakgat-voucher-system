import os
import unittest
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app import gce_entry as gce
from app import merchant_finance as finance


class MerchantSettlementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        gce.LocalPartnerProduct.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-TEST",
            display_name="تاجر الاختبار",
            contact_phone="966500000000",
            status="active",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.link = finance.MerchantProductLink(
            merchant_id=self.merchant.id,
            product_id="product-1",
            sku="PKG-QR-TEST",
            product_name_snapshot="عرض الاختبار",
            commission_percent=Decimal("20.00"),
            product_status="active",
        )
        self.db.add(self.link)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _redeemed_voucher(self):
        voucher = core.Voucher(
            code="PKG-SETTLE",
            verification_token="token-settle",
            order_id="order-1:product-1:1",
            product_id="product-1",
            product_name="عرض الاختبار",
            merchant_name="تاجر الاختبار",
            status="redeemed",
            created_at=core.now_utc(),
            expires_at=core.now_utc(),
            redeemed_at=core.now_utc(),
        )
        self.db.add(voucher)
        self.db.flush()
        self.db.add(
            finance.VoucherFinancialSnapshot(
                voucher_id=voucher.id,
                merchant_id=self.merchant.id,
                order_id=voucher.order_id,
                product_id=voucher.product_id,
                gross_amount=Decimal("100.00"),
                commission_percent=Decimal("20.00"),
                currency="SAR",
            )
        )
        self.db.commit()
        return voucher

    def test_redeemed_voucher_creates_single_payable_with_snapshot_commission(self):
        voucher = self._redeemed_voucher()
        first = finance.ensure_payable_for_redeemed_voucher(self.db, voucher)
        second = finance.ensure_payable_for_redeemed_voucher(self.db, voucher)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Decimal(first.commission_percent), Decimal("20.00"))
        self.assertEqual(Decimal(first.commission_amount), Decimal("20.00"))
        self.assertEqual(Decimal(first.merchant_amount), Decimal("80.00"))

        self.link.commission_percent = Decimal("10.00")
        self.db.commit()
        self.db.refresh(first)
        self.assertEqual(Decimal(first.commission_percent), Decimal("20.00"))
        self.assertEqual(Decimal(first.merchant_amount), Decimal("80.00"))

    def test_expired_voucher_creates_no_merchant_payable(self):
        voucher = core.Voucher(
            code="PKG-EXPIRED",
            verification_token="token-expired",
            order_id="order-expired:product-1:1",
            product_id="product-1",
            product_name="عرض الاختبار",
            merchant_name="تاجر الاختبار",
            status="expired",
            created_at=core.now_utc(),
            expires_at=core.now_utc(),
        )
        self.db.add(voucher)
        self.db.commit()
        self.assertIsNone(finance.ensure_payable_for_redeemed_voucher(self.db, voucher))

    def test_paid_settlement_cannot_be_included_or_paid_twice(self):
        voucher = self._redeemed_voucher()
        payable = finance.ensure_payable_for_redeemed_voucher(self.db, voucher)
        batch = finance.build_weekly_settlement_batch(self.db, self.merchant.id)
        self.assertIsNotNone(batch)
        self.db.refresh(payable)
        self.assertEqual(payable.status, "batched")
        self.assertEqual(Decimal(batch.payable_amount), Decimal("80.00"))

        finance.approve_settlement_batch(self.db, batch.id)
        payment = finance.record_settlement_payment(
            self.db,
            batch.id,
            amount=Decimal("80.00"),
            bank_reference="TRX-001",
            bank_name="Test Bank",
            iban_snapshot="SA000000",
            recorded_by="admin",
        )
        duplicate = finance.record_settlement_payment(
            self.db,
            batch.id,
            amount=Decimal("80.00"),
            bank_reference="TRX-002",
        )
        self.assertEqual(payment.id, duplicate.id)
        self.assertEqual(duplicate.bank_reference, "TRX-001")
        self.assertIsNone(finance.build_weekly_settlement_batch(self.db, self.merchant.id))


if __name__ == "__main__":
    unittest.main()
