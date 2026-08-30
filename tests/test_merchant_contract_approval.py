import json
import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance


class MerchantContractApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        contracts.ensure_merchant_contract_schema(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-APPROVAL",
            display_name="تام العاصمة",
            legal_name="تام العاصمة للتجارة",
            commercial_registration="1010101010",
            tax_number="310000000000003",
            contact_phone="966504161514",
            contact_email="merchant@example.test",
            iban="SA0012345678901234567890",
            bank_name="Test Bank",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            status="draft",
        )
        self.db.add(self.contract)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_approval_audit_model_has_required_snapshot_fields(self):
        self.assertTrue(hasattr(contracts, "MerchantContractApproval"))
        columns = contracts.MerchantContractApproval.__table__.c
        for name in (
            "merchant_contract_id",
            "merchant_id",
            "agreement_number_snapshot",
            "approved_at",
            "pakgat_signer_name",
            "pakgat_signer_title",
            "pakgat_signer_phone",
            "merchant_snapshot_json",
            "template_version",
        ):
            self.assertIn(name, columns)

    def test_approve_contract_records_pakgat_approval_without_activating_merchant(self):
        approved_at = datetime(2026, 8, 30, 18, 45, tzinfo=timezone.utc)

        approval = contracts.approve_contract(
            self.db,
            self.contract,
            approved_at=approved_at,
        )

        self.db.refresh(self.contract)
        self.db.refresh(self.merchant)
        self.assertEqual(approval.merchant_contract_id, self.contract.id)
        self.assertEqual(self.contract.status, "approved_internal")
        self.assertEqual(self.contract.agreement_number, "PKG-MA-2026-08-0001")
        self.assertEqual(approval.agreement_number_snapshot, self.contract.agreement_number)
        self.assertEqual(approval.approved_at.replace(tzinfo=timezone.utc), approved_at)
        self.assertEqual(approval.pakgat_signer_name, "بهاء السقا")
        self.assertEqual(approval.pakgat_signer_title, "مدير تطوير الأعمال")
        self.assertEqual(approval.pakgat_signer_phone, "0504161514")
        self.assertEqual(self.merchant.status, "pending")

    def test_approval_snapshot_does_not_change_when_merchant_profile_changes(self):
        approved_at = datetime(2026, 8, 30, 18, 45, tzinfo=timezone.utc)
        approval = contracts.approve_contract(self.db, self.contract, approved_at=approved_at)
        snapshot_before = json.loads(approval.merchant_snapshot_json)

        self.merchant.legal_name = "اسم قانوني معدل لاحقًا"
        self.merchant.iban = "SA9999999999999999999999"
        self.db.commit()
        self.db.refresh(approval)

        snapshot_after = json.loads(approval.merchant_snapshot_json)
        self.assertEqual(snapshot_before, snapshot_after)
        self.assertEqual(snapshot_after["legal_name"], "تام العاصمة للتجارة")
        self.assertEqual(snapshot_after["iban"], "SA0012345678901234567890")

    def test_approval_is_idempotent_and_keeps_original_number_and_date(self):
        first_time = datetime(2026, 8, 30, 18, 45, tzinfo=timezone.utc)
        later_time = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)

        first = contracts.approve_contract(self.db, self.contract, approved_at=first_time)
        first_number = self.contract.agreement_number
        first_snapshot = first.merchant_snapshot_json

        second = contracts.approve_contract(self.db, self.contract, approved_at=later_time)
        self.db.refresh(self.contract)

        self.assertEqual(second.id, first.id)
        self.assertEqual(self.contract.agreement_number, first_number)
        self.assertEqual(second.approved_at.replace(tzinfo=timezone.utc), first_time)
        self.assertEqual(second.merchant_snapshot_json, first_snapshot)
        count = len(
            self.db.scalars(
                select(contracts.MerchantContractApproval).where(
                    contracts.MerchantContractApproval.merchant_contract_id == self.contract.id
                )
            ).all()
        )
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
