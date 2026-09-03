import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_profile_admin as profile_admin


class MerchantContractAdminTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine, checkfirst=True)
        core.AuditLog.__table__.create(self.engine, checkfirst=True)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine, checkfirst=True)
        contracts.MerchantContractApproval.__table__.create(self.engine, checkfirst=True)
        for table in onboarding.ONBOARDING_TABLES:
            table.create(self.engine, checkfirst=True)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-ADMIN",
            display_name="Admin Merchant",
            legal_name="Admin Merchant LLC",
            contact_phone="0500000000",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0099",
            status="signed",
            sadq_document_id="sadq-doc-99",
            sadq_transaction_id="sadq-request-99",
            signed_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.db.add(self.contract)
        self.db.flush()
        self.delivery = finance.MerchantContractDelivery(
            merchant_contract_id=self.contract.id,
            merchant_id=self.merchant.id,
            channel="whatsapp",
            destination="966500000000",
            status="failed",
            attempt_count=2,
            provider_message_id="text_sent",
            last_error="whatsloop_document_sender_not_configured",
        )
        self.db.add(self.delivery)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self, path, method="GET"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [],
                "query_string": b"",
                "scheme": "https",
                "server": ("example.test", 443),
                "client": ("127.0.0.1", 12345),
            }
        )

    def test_retry_route_is_registered(self):
        paths = {
            getattr(route, "path", "")
            for route in core.app.routes
            if "POST" in (getattr(route, "methods", set()) or set())
        }
        self.assertIn(
            "/admin/merchants/{merchant_id}/contracts/{contract_id}/retry-whatsapp",
            paths,
        )

    def test_admin_retry_requires_auth(self):
        response = contracts.admin_retry_contract_whatsapp(
            self.merchant.id,
            self.contract.id,
            self._request("/retry", "POST"),
            self.db,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/admin/login", response.headers["location"])

    def test_retry_reuses_existing_delivery_row(self):
        with patch.object(contracts.core, "require_admin", return_value=None), patch.object(
            contracts, "deliver_signed_contract", return_value=self.delivery
        ) as deliver:
            response = contracts.admin_retry_contract_whatsapp(
                self.merchant.id,
                self.contract.id,
                self._request("/retry", "POST"),
                self.db,
            )
        self.assertEqual(response.status_code, 303)
        deliver.assert_called_once()
        self.assertEqual(
            self.db.query(finance.MerchantContractDelivery).count(),
            1,
        )
        self.assertEqual(
            self.db.query(finance.MerchantContractDelivery).first().id,
            self.delivery.id,
        )

    def test_retry_rejects_unsigned_contract(self):
        self.contract.status = "sent"
        self.db.commit()
        with patch.object(contracts.core, "require_admin", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                contracts.admin_retry_contract_whatsapp(
                    self.merchant.id,
                    self.contract.id,
                    self._request("/retry", "POST"),
                    self.db,
                )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_contract_summary_shows_signed_and_delivery_audit(self):
        html = contracts.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertIn("PKG-MA-2026-08-0099", html)
        self.assertIn("sadq-doc-99", html)
        self.assertIn("sadq-request-99", html)
        self.assertIn("failed", html)
        self.assertIn("2", html)
        self.assertIn("whatsloop_document_sender_not_configured", html)
        self.assertIn("إعادة إرسال", html)

    def test_existing_merchant_detail_page_includes_contract_summary(self):
        with patch.object(profile_admin.core, "require_admin", return_value=None):
            response = profile_admin._merchant_detail_with_edit(
                self.merchant.id,
                self._request(f"/admin/merchants/{self.merchant.id}"),
                self.db,
            )
        html = response.body.decode("utf-8")
        self.assertIn("PKG-MA-2026-08-0099", html)
        self.assertIn("حالة إرسال نسخة العقد", html)


if __name__ == "__main__":
    unittest.main()
