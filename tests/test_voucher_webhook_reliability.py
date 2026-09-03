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


class VoucherWebhookReliabilityTests(unittest.TestCase):
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
                "id": "order-100",
                "payment_status": "paid",
                "customer": {
                    "name": "Test Customer",
                    "mobile": "0500000000",
                },
                "items": [
                    {
                        "id": "product-10",
                        "name": "Test Voucher",
                        "sku": "PKG-QR-TEST",
                        "quantity": 1,
                    }
                ],
            },
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self):
        body = json.dumps(self.payload).encode("utf-8")
        signature = hmac.new(
            self.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
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

    def _deliver(self):
        tasks = BackgroundTasks()
        with patch.object(core, "SALLA_WEBHOOK_SECRET", self.secret), patch.object(
            core, "fetch_salla_product_metadata", return_value=(None, "not needed")
        ):
            result = asyncio.run(core.salla_webhook(self._request(), tasks, self.db))
        return result, tasks

    def test_replayed_paid_webhook_retries_unsent_customer_notification(self):
        first_result, first_tasks = self._deliver()
        self.assertEqual(first_result["created_count"], 1)
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(core.Voucher)), 1
        )
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(core.CustomerNotification)
            ),
            1,
        )
        self.assertFalse(
            any(task.func is core.send_voucher_whatsapp for task in first_tasks.tasks),
            "The direct sender must not run alongside the durable outbox.",
        )

        replay_result, replay_tasks = self._deliver()
        self.assertEqual(replay_result["created_count"], 0)
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(core.CustomerNotification)
            ),
            1,
            "A replay must preserve exactly one retryable logical notification.",
        )
        notification = self.db.scalar(select(core.CustomerNotification))
        self.assertEqual(notification.status, "queued")
        self.assertFalse(
            any(task.func is core.send_voucher_whatsapp for task in replay_tasks.tasks)
        )


if __name__ == "__main__":
    unittest.main()
