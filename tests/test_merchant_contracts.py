import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import HTTPException
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_finance as finance
from app import merchant_contracts as contracts


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
        number = finance.next_agreement_number(
            self.db,
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.assertRegex(number, r"^PKG-MA-2026-08-\d{4}$")

    def test_agreement_number_sequence_advances_within_month(self):
        merchant = finance.Merchant(code="PKG-M-TEST01", display_name="Test Merchant")
        self.db.add(merchant)
        self.db.flush()
        self.db.add(
            finance.MerchantContract(
                merchant_id=merchant.id,
                agreement_number="PKG-MA-2026-08-0007",
                status="draft",
            )
        )
        self.db.commit()
        number = finance.next_agreement_number(
            self.db,
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(number, "PKG-MA-2026-08-0008")

    def test_delivery_is_unique_per_contract_and_channel(self):
        merchant = finance.Merchant(code="PKG-M-TEST02", display_name="Delivery Merchant")
        self.db.add(merchant)
        self.db.flush()
        contract = finance.MerchantContract(merchant_id=merchant.id, status="signed")
        self.db.add(contract)
        self.db.flush()
        self.db.add(
            finance.MerchantContractDelivery(
                merchant_contract_id=contract.id,
                merchant_id=merchant.id,
                channel="whatsapp",
                destination="966500000000",
                status="pending",
            )
        )
        self.db.commit()
        self.db.add(
            finance.MerchantContractDelivery(
                merchant_contract_id=contract.id,
                merchant_id=merchant.id,
                channel="whatsapp",
                destination="966500000000",
                status="pending",
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_existing_contract_table_is_upgraded_additively(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        try:
            with legacy_engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE merchant_contracts (
                        id INTEGER PRIMARY KEY,
                        merchant_id INTEGER NOT NULL,
                        status VARCHAR(40),
                        sadq_document_id VARCHAR(255),
                        sadq_transaction_id VARCHAR(255),
                        signed_document_url VARCHAR(1000),
                        signed_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
            contracts.ensure_merchant_contract_schema(legacy_engine)
            columns = {column["name"] for column in inspect(legacy_engine).get_columns("merchant_contracts")}
            self.assertIn("agreement_number", columns)
            tables = set(inspect(legacy_engine).get_table_names())
            self.assertIn("merchant_contract_deliveries", tables)
        finally:
            legacy_engine.dispose()


class MerchantSadqWebhookTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-WEBHOOK",
            display_name="Webhook Merchant",
            contact_phone="0500000000",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0047",
            status="sent",
            sadq_document_id="sadq-doc-47",
            sadq_transaction_id="sadq-request-47",
        )
        self.db.add(self.contract)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self, payload, token="webhook-test-token"):
        body = json.dumps(payload).encode("utf-8")
        headers = []
        if token:
            headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
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
                "headers": headers,
                "query_string": b"",
                "scheme": "https",
                "server": ("example.test", 443),
                "client": ("127.0.0.1", 12345),
            },
            receive,
        )

    def _completed_payload(self):
        return {
            "requestId": self.contract.sadq_transaction_id,
            "documentId": self.contract.sadq_document_id,
            "status": 2,
        }

    def test_invalid_webhook_token_does_not_change_contract(self):
        with patch.object(contracts, "SADQ_WEBHOOK_TOKEN", "webhook-test-token"):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(contracts.sadq_webhook(self._request(self._completed_payload(), "wrong"), self.db))
        self.assertEqual(ctx.exception.status_code, 403)
        self.db.refresh(self.contract)
        self.assertEqual(self.contract.status, "sent")

    def test_completed_webhook_marks_contract_signed_without_activating_merchant(self):
        with patch.object(contracts, "SADQ_WEBHOOK_TOKEN", "webhook-test-token"):
            result = asyncio.run(contracts.sadq_webhook(self._request(self._completed_payload()), self.db))
        self.assertEqual(result["status"], "signed")
        self.db.refresh(self.contract)
        self.db.refresh(self.merchant)
        self.assertEqual(self.contract.status, "signed")
        self.assertIsNotNone(self.contract.signed_at)
        self.assertEqual(self.merchant.status, "pending")

    def test_duplicate_completed_webhook_is_idempotent(self):
        with patch.object(contracts, "SADQ_WEBHOOK_TOKEN", "webhook-test-token"):
            asyncio.run(contracts.sadq_webhook(self._request(self._completed_payload()), self.db))
            asyncio.run(contracts.sadq_webhook(self._request(self._completed_payload()), self.db))
        note_count = self.db.scalar(
            select(func.count(finance.MerchantNote.id)).where(
                finance.MerchantNote.merchant_id == self.merchant.id,
                finance.MerchantNote.note_type == "contract",
            )
        )
        self.assertEqual(note_count, 1)

    def test_rejected_callback_updates_only_contract_status(self):
        payload = self._completed_payload()
        payload["status"] = 4
        with patch.object(contracts, "SADQ_WEBHOOK_TOKEN", "webhook-test-token"):
            result = asyncio.run(contracts.sadq_webhook(self._request(payload), self.db))
        self.db.refresh(self.contract)
        self.db.refresh(self.merchant)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.contract.status, "rejected")
        self.assertEqual(self.merchant.status, "pending")


if __name__ == "__main__":
    unittest.main()
