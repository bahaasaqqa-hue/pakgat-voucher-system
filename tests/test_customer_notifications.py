import os
import unittest
import asyncio
from unittest.mock import patch
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app.customer_notifications import dispatch_due_customer_notifications


class CustomerNotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.CustomerNotification.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.voucher = core.create_voucher_record(
            self.db, "order:product:1", "product", "عرض", "شريك",
            "عميل", "0500000000", None,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_dispatcher_retries_failure_then_marks_sent(self):
        row = core.ensure_customer_notification(
            self.db, self.voucher, "voucher_issued", "message"
        )

        first = dispatch_due_customer_notifications(
            self.db, lambda phone, body: (_ for _ in ()).throw(TimeoutError("secret"))
        )
        self.assertEqual(first.failed, 1)
        self.db.refresh(row)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempt_count, 1)
        self.assertNotIn("secret", row.last_error)

        row.next_attempt_at = None
        self.db.commit()
        second = dispatch_due_customer_notifications(self.db, lambda phone, body: None)
        self.assertEqual(second.sent, 1)
        self.db.refresh(row)
        self.assertEqual(row.status, "sent")
        self.assertIsNotNone(row.sent_at)

    def test_approved_prompts_are_part_of_existing_messages(self):
        issued = core.build_voucher_whatsapp_message(
            "عميل", "عرض", "PKG-X", "100", "https://example.test/v/x"
        )
        redeemed = core.build_redemption_whatsapp_message(
            "عميل", "عرض", "PKG-X", "100", "شريك", core.now_utc()
        )
        self.assertIn("1 — وصلتني القسيمة", issued)
        self.assertIn("2 — أحتاج مساعدة", issued)
        self.assertIn("من 1 إلى 5", redeemed)

    def test_admin_voucher_creation_queues_the_real_customer_message(self):
        body = (
            b"order_id=ADMIN-TEST&product_id=P1&product_name=Test+Offer&"
            b"merchant_name=Pakgat&customer_name=Test&customer_phone=0504161514&"
            b"validity_days=7"
        )
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": "POST", "path": "/admin/vouchers/new", "headers": []}, receive=receive)
        with patch.object(core, "require_admin", return_value=True):
            response = asyncio.run(core.admin_create_voucher(request, self.db))

        self.assertEqual(response.status_code, 303)
        row = self.db.scalar(select(core.CustomerNotification))
        self.assertIsNotNone(row)
        self.assertEqual(row.notification_type, "voucher_issued")
        self.assertEqual(row.customer_phone, "966504161514")
        self.assertIn("1 — وصلتني القسيمة", row.message_body)


if __name__ == "__main__":
    unittest.main()
