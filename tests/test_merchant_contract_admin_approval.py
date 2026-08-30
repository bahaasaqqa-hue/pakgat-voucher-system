import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_contract_admin_actions as actions
from app import merchant_finance as finance


class MerchantContractAdminApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        contracts.ensure_merchant_contract_schema(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-ADMIN-APPROVAL",
            display_name="تام العاصمة",
            legal_name="تام العاصمة للتجارة",
            contact_phone="966504161514",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _request(self, path, method="POST"):
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

    def test_create_and_approve_routes_are_registered(self):
        paths = {
            getattr(route, "path", "")
            for route in core.app.routes
            if "POST" in (getattr(route, "methods", set()) or set())
        }
        self.assertIn("/admin/merchants/{merchant_id}/contracts/create-draft", paths)
        self.assertIn("/admin/merchants/{merchant_id}/contracts/{contract_id}/approve", paths)

    def test_no_contract_summary_offers_create_draft(self):
        html = actions.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertIn("إنشاء مسودة عقد", html)
        self.assertIn(f"/admin/merchants/{self.merchant.id}/contracts/create-draft", html)

    def test_create_draft_requires_admin_auth(self):
        response = actions.admin_create_contract_draft(
            self.merchant.id,
            self._request("/create"),
            self.db,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/admin/login", response.headers["location"])
        self.assertIsNone(
            self.db.scalar(
                select(finance.MerchantContract).where(
                    finance.MerchantContract.merchant_id == self.merchant.id
                )
            )
        )

    def test_create_draft_then_summary_offers_pakgat_approval(self):
        with patch.object(contracts.core, "require_admin", return_value=None):
            response = actions.admin_create_contract_draft(
                self.merchant.id,
                self._request("/create"),
                self.db,
            )
        self.assertEqual(response.status_code, 303)
        contract = self.db.scalar(
            select(finance.MerchantContract).where(
                finance.MerchantContract.merchant_id == self.merchant.id
            )
        )
        self.assertIsNotNone(contract)
        self.assertEqual(contract.status, "draft")
        self.assertIsNone(contract.agreement_number)

        html = actions.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertIn("اعتماد العقد من Pakgat", html)
        self.assertIn(
            f"/admin/merchants/{self.merchant.id}/contracts/{contract.id}/approve",
            html,
        )

    def test_admin_approval_freezes_contract_and_shows_pakgat_signer(self):
        contract = finance.MerchantContract(merchant_id=self.merchant.id, status="draft")
        self.db.add(contract)
        self.db.commit()

        with patch.object(contracts.core, "require_admin", return_value=None):
            response = actions.admin_approve_contract(
                self.merchant.id,
                contract.id,
                self._request("/approve"),
                self.db,
            )
        self.assertEqual(response.status_code, 303)
        self.db.refresh(contract)
        self.assertEqual(contract.status, "approved_internal")
        self.assertIsNotNone(contract.agreement_number)

        approval = self.db.scalar(
            select(contracts.MerchantContractApproval).where(
                contracts.MerchantContractApproval.merchant_contract_id == contract.id
            )
        )
        self.assertIsNotNone(approval)
        html = actions.merchant_contract_summary_html(self.db, self.merchant.id)
        self.assertIn("بهاء السقا", html)
        self.assertIn("مدير تطوير الأعمال", html)
        self.assertIn("اعتماد Pakgat", html)


if __name__ == "__main__":
    unittest.main()
