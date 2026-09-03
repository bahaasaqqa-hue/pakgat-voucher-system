import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_contract_admin_actions as actions
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding


class MerchantContractAdminApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        contracts.ensure_merchant_contract_schema(self.engine)
        for table in onboarding.ONBOARDING_TABLES:
            table.create(self.engine, checkfirst=True)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-ADMIN-APPROVAL",
            display_name="تام العاصمة",
            legal_name="تام العاصمة للتجارة",
            contact_phone="966504161514",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.application = onboarding.MerchantOnboardingApplication(
            merchant_id=self.merchant.id,
            status="pending_review",
        )
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0200",
            status="signed",
            signed_at=core.now_utc(),
        )
        self.db.add_all([self.application, self.contract])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self, path, method="POST"):
        return Request({
            "type": "http", "method": method, "path": path, "headers": [],
            "query_string": b"", "scheme": "https", "server": ("example.test", 443),
            "client": ("127.0.0.1", 12345),
        })

    def test_only_post_sadq_review_routes_are_registered(self):
        paths = {
            getattr(route, "path", "")
            for route in core.app.routes
            if "POST" in (getattr(route, "methods", set()) or set())
        }
        self.assertIn("/admin/merchants/{merchant_id}/contracts/{contract_id}/approve-onboarding", paths)
        self.assertIn("/admin/merchants/{merchant_id}/onboarding/request-changes", paths)
        self.assertIn("/admin/merchants/{merchant_id}/onboarding/reject", paths)
        self.assertNotIn("/admin/merchants/{merchant_id}/contracts/create-draft", paths)
        self.assertNotIn("/admin/merchants/{merchant_id}/contracts/{contract_id}/approve", paths)

    def test_summary_offers_review_actions_only_after_signed(self):
        html = actions.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertIn("بانتظار مراجعة Pakgat", html)
        self.assertIn("اعتماد التاجر", html)
        self.assertIn("طلب استكمال", html)
        self.assertIn("رفض الطلب", html)
        self.assertNotIn("إنشاء مسودة عقد", html)
        self.assertNotIn("اعتماد العقد من Pakgat", html)

        self.contract.status = "sadq_pending"
        self.application.status = "sadq_pending"
        self.db.commit()
        html = actions.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertNotIn("اعتماد التاجر", html)

    def test_approve_route_requires_admin_auth(self):
        response = actions.admin_approve_onboarding(
            self.merchant.id,
            self.contract.id,
            self._request("/approve"),
            self.db,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/admin/login", response.headers["location"])
        self.db.refresh(self.merchant)
        self.assertEqual(self.merchant.status, "pending")

    def test_admin_approval_after_sadq_activates_merchant_and_records_signer(self):
        with patch.object(contracts.core, "require_admin", return_value=None):
            response = actions.admin_approve_onboarding(
                self.merchant.id,
                self.contract.id,
                self._request("/approve"),
                self.db,
            )
        self.assertEqual(response.status_code, 303)
        self.db.refresh(self.contract)
        self.db.refresh(self.merchant)
        self.db.refresh(self.application)
        self.assertEqual(self.contract.status, "approved")
        self.assertEqual(self.merchant.status, "active")
        self.assertEqual(self.application.status, "approved")
        approval = self.db.scalar(select(contracts.MerchantContractApproval).where(contracts.MerchantContractApproval.merchant_contract_id == self.contract.id))
        self.assertIsNotNone(approval)
        self.assertEqual(approval.pakgat_signer_name, "بهاء السقا")
        self.assertEqual(approval.pakgat_signer_title, "مدير تطوير الأعمال")


if __name__ == "__main__":
    unittest.main()
