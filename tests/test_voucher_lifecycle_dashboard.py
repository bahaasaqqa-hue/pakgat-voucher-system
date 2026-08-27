import importlib.util
import os
import unittest
from datetime import timedelta
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


class VoucherLifecycleDashboardTests(unittest.TestCase):
    def test_lifecycle_dashboard_extension_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("app.voucher_lifecycle_dashboard"))

    def test_expiry_sweep_marks_unused_due_voucher_expired_and_reports_values(self):
        from app import voucher_lifecycle_dashboard as dashboard

        engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(engine)
        core.AuditLog.__table__.create(engine)
        finance.VoucherFinancialSnapshot.__table__.create(engine)
        db = Session(engine)
        try:
            expired = core.Voucher(
                code="PKG-EXP-DASH",
                verification_token="token-exp-dash",
                order_id="order-exp:product-1:1",
                product_id="product-1",
                product_name="Expired Product",
                merchant_name="Merchant",
                status="active",
                created_at=core.now_utc() - timedelta(days=10),
                expires_at=core.now_utc() - timedelta(days=1),
            )
            refunded = core.Voucher(
                code="PKG-REF-DASH",
                verification_token="token-ref-dash",
                order_id="order-ref:product-2:1",
                product_id="product-2",
                product_name="Refunded Product",
                merchant_name="Merchant",
                status="refunded",
                created_at=core.now_utc() - timedelta(days=3),
                expires_at=core.now_utc() + timedelta(days=4),
            )
            db.add_all([expired, refunded])
            db.flush()
            db.add_all([
                finance.VoucherFinancialSnapshot(
                    voucher_id=expired.id,
                    order_id=expired.order_id,
                    product_id=expired.product_id,
                    gross_amount=Decimal("150.00"),
                    currency="SAR",
                ),
                finance.VoucherFinancialSnapshot(
                    voucher_id=refunded.id,
                    order_id=refunded.order_id,
                    product_id=refunded.product_id,
                    gross_amount=Decimal("75.00"),
                    currency="SAR",
                ),
            ])
            db.commit()

            changed = dashboard.expire_due_vouchers(db)
            db.refresh(expired)
            self.assertEqual(changed, 1)
            self.assertEqual(expired.status, "expired")

            html = dashboard.voucher_lifecycle_finance_html(db)
            self.assertIn("Expired بدون استخدام", html)
            self.assertIn("150.00", html)
            self.assertIn("Refunded", html)
            self.assertIn("75.00", html)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
