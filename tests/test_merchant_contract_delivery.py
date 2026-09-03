import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance


class _FakePDFResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return b"%PDF-1.7 signed contract"


class MerchantContractDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-DELIVERY",
            display_name="Delivery Merchant",
            contact_phone="0500000000",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0047",
            status="signed",
            sadq_document_id="sadq-doc-47",
            sadq_transaction_id="sadq-request-47",
            signed_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.db.add(self.contract)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_signed_pdf_download_uses_document_endpoint_and_bearer(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakePDFResponse()

        with patch.object(contracts, "SADQ_API_BASE_URL", "https://sandbox-api.sadq-sa.com"), patch.object(
            contracts, "SADQ_BEARER_TOKEN", "sadq-test-token"
        ), patch.object(contracts, "urlopen", fake_urlopen):
            ok, content, error = contracts.download_signed_sadq_pdf("sadq-doc-47")

        self.assertTrue(ok)
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(error, "")
        self.assertEqual(
            captured["request"].full_url,
            "https://sandbox-api.sadq-sa.com/api/v1/documents/sadq-doc-47/signed",
        )
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer sadq-test-token")
        self.assertEqual(captured["request"].get_header("Accept"), "application/pdf")

    def test_pdf_retrieval_failure_keeps_signed_and_records_failed_delivery(self):
        with patch.object(
            contracts,
            "download_signed_sadq_pdf",
            return_value=(False, None, "sadq_http_502"),
        ):
            delivery = contracts.deliver_signed_contract(self.db, self.contract)
        self.db.refresh(self.contract)
        self.assertEqual(self.contract.status, "signed")
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error, "sadq_http_502")

    def test_missing_merchant_phone_records_failure(self):
        self.merchant.contact_phone = None
        self.db.commit()
        delivery = contracts.deliver_signed_contract(self.db, self.contract)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.last_error, "merchant_contact_phone_missing")
        self.assertEqual(delivery.attempt_count, 1)

    def test_text_notification_is_truthful_and_document_gap_is_audited(self):
        with patch.object(
            contracts,
            "download_signed_sadq_pdf",
            return_value=(True, b"%PDF-1.7", ""),
        ), patch.object(
            contracts,
            "_send_whatsloop_text",
            return_value=(True, "HTTP 200: sent"),
        ) as send_text:
            delivery = contracts.deliver_signed_contract(self.db, self.contract)

        send_text.assert_called_once()
        phone, message = send_text.call_args.args
        self.assertEqual(phone, "966500000000")
        self.assertIn("PKG-MA-2026-08-0047", message)
        self.assertIn("تم توقيع اتفاقية الشراكة", message)
        self.assertNotIn("أرفقنا", message)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.last_error, "whatsloop_document_sender_not_configured")
        self.assertTrue(delivery.provider_message_id)

    def test_retry_after_text_success_does_not_duplicate_text(self):
        with patch.object(
            contracts,
            "download_signed_sadq_pdf",
            return_value=(True, b"%PDF-1.7", ""),
        ), patch.object(
            contracts,
            "_send_whatsloop_text",
            return_value=(True, "HTTP 200: sent"),
        ) as send_text:
            first = contracts.deliver_signed_contract(self.db, self.contract)
            second = contracts.deliver_signed_contract(self.db, self.contract)

        self.assertEqual(first.id, second.id)
        self.assertEqual(send_text.call_count, 1)
        self.assertEqual(second.attempt_count, 2)

    def test_already_sent_delivery_is_idempotent(self):
        delivery = finance.MerchantContractDelivery(
            merchant_contract_id=self.contract.id,
            merchant_id=self.merchant.id,
            channel="whatsapp",
            destination="966500000000",
            status="sent",
            attempt_count=1,
            provider_message_id="provider-123",
            sent_at=core.now_utc(),
        )
        self.db.add(delivery)
        self.db.commit()
        with patch.object(contracts, "download_signed_sadq_pdf") as download, patch.object(
            contracts, "_send_whatsloop_text"
        ) as send_text:
            result = contracts.deliver_signed_contract(self.db, self.contract)
        self.assertEqual(result.id, delivery.id)
        download.assert_not_called()
        send_text.assert_not_called()


class MerchantSignedWebhookDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)
        merchant = finance.Merchant(
            code="PKG-M-WEBHOOK-DELIVERY",
            display_name="Webhook Delivery Merchant",
            contact_phone="0500000000",
            status="pending",
        )
        self.db.add(merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=merchant.id,
            agreement_number="PKG-MA-2026-08-0048",
            status="sent",
            sadq_document_id="sadq-doc-48",
            sadq_transaction_id="sadq-request-48",
        )
        self.db.add(self.contract)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self):
        body = json.dumps(
            {
                "requestId": self.contract.sadq_transaction_id,
                "documentId": self.contract.sadq_document_id,
                "status": 2,
            }
        ).encode("utf-8")
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
                "path": "/integrations/sadq/webhook",
                "headers": [(b"authorization", b"Bearer webhook-test-token")],
                "query_string": b"",
                "scheme": "https",
                "server": ("example.test", 443),
                "client": ("127.0.0.1", 12345),
            },
            receive,
        )

    def test_only_first_signed_transition_triggers_delivery(self):
        with patch.object(contracts, "SADQ_WEBHOOK_TOKEN", "webhook-test-token"), patch.object(
            contracts, "deliver_signed_contract", return_value=None
        ) as deliver:
            asyncio.run(contracts.sadq_webhook(self._request(), self.db))
            asyncio.run(contracts.sadq_webhook(self._request(), self.db))
        deliver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
