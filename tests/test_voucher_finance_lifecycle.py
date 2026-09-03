import asyncio
import hashlib
import hmac
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_finance_hooks  # noqa: F401 - activate lifecycle hooks


class VoucherFinanceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.secret = "refund-secret"

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _voucher(self, code, status="active"):
        voucher = core.Voucher(
            code=code,
            verification_token="token-" + code,
            order_id="order-refund:product-1:1" if code.endswith("1") else "order-refund:product-2:1",
            product_id="product-1" if code.endswith("1") else "product-2",
            product_name="عرض",
            merchant_name="تاجر",
            status=status,
            created_at=core.now_utc(),
            expires_at=core.now_utc(),
            redeemed_at=core.now_utc() if status == "redeemed" else None,
        )
        self.db.add(voucher)
        self.db.commit()
        return voucher

    def _request(self, event, items=None):
        payload = {
            "event": event,
            "data": {
                "id": "order-refund",
                "items": items or [],
            },
        }
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/webhooks/salla",
                "headers": [(b"x-salla-signature", signature.encode("ascii"))],
            },
            receive=receive,
        )

    def test_refund_changes_active_but_never_silently_reverses_redeemed(self):
        active = self._voucher("PKG-1", "active")
        redeemed = self._voucher("PKG-2", "redeemed")
        with unittest.mock.patch.object(core, "SALLA_WEBHOOK_SECRET", self.secret):
            result = asyncio.run(
                core.salla_webhook(self._request("order.refunded"), BackgroundTasks(), self.db)
            )
        self.db.refresh(active)
        self.db.refresh(redeemed)
        self.assertEqual(active.status, "refunded")
        self.assertEqual(redeemed.status, "redeemed")
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["redeemed_review"], 1)
        review = self.db.scalar(
            select(core.AuditLog).where(
                core.AuditLog.voucher_id == redeemed.id,
                core.AuditLog.action == "refund_after_redemption_review",
            )
        )
        self.assertIsNotNone(review)

    def test_cancel_revokes_only_matching_active_product_when_items_are_present(self):
        first = self._voucher("PKG-1", "active")
        second = self._voucher("PKG-2", "active")
        items = [{"id": "product-1", "product_id": "product-1"}]
        with unittest.mock.patch.object(core, "SALLA_WEBHOOK_SECRET", self.secret):
            result = asyncio.run(
                core.salla_webhook(self._request("order.cancelled", items), BackgroundTasks(), self.db)
            )
        self.db.refresh(first)
        self.db.refresh(second)
        self.assertEqual(first.status, "revoked")
        self.assertEqual(second.status, "active")
        self.assertEqual(result["changed"], 1)


if __name__ == "__main__":
    unittest.main()
