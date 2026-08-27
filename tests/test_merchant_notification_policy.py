import asyncio
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import BackgroundTasks
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_finance as finance  # noqa: F401 - activates finance extension


class MerchantNotificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        core.MerchantNotification.__table__.create(self.engine)
        core.CustomerNotification.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.secret = "test-salla-secret"
        self.payload = {
            "event": "order.payment.updated",
            "merchant": {"id": "merchant-1", "name": "Pakgat"},
            "data": {
                "id": "order-policy",
                "payment_status": "paid",
                "customer": {"name": "Customer", "mobile": "0500000000"},
                "items": [{"id": "product-policy", "name": "Voucher", "sku": "PKG-QR-POLICY", "quantity": 1}],
            },
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self):
        body = json.dumps(self.payload).encode("utf-8")
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

    def test_paid_order_does_not_notify_merchant_before_redemption(self):
        tasks = BackgroundTasks()
        metadata = [
            {"label": "اسم الشريك", "value": "Partner"},
            {"label": "رقم جوال استقبال القسائم", "value": "0500000001"},
        ]
        with patch.object(core, "SALLA_WEBHOOK_SECRET", self.secret), patch.object(
            core, "fetch_salla_product_metadata", return_value=(metadata, None)
        ):
            result = asyncio.run(core.salla_webhook(self._request(), tasks, self.db))
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(core.MerchantNotification)),
            0,
            "Purchase-time merchant sale notifications must be disabled.",
        )
        self.assertFalse(
            any(task.func is core.send_merchant_sale_whatsapp for task in tasks.tasks),
            "Merchant must only be notified after redemption.",
        )


if __name__ == "__main__":
    unittest.main()
