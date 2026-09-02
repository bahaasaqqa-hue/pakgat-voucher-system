"""Regression tests for the manual merchant contract signing workflow.

The merchant downloads the generated Pakgat agreement, signs/stamps it,
uploads the signed PDF, then Pakgat uploads the final jointly executed PDF.
No Sadq/Nafath step participates in this onboarding path.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-password")
os.environ.setdefault("ADMIN_SECRET", "test-only-admin-secret")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-secret")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_manual_contract as manual


class ManualMerchantContractFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("MERCHANT_DOCUMENT_ROOT")
        os.environ["MERCHANT_DOCUMENT_ROOT"] = self.tempdir.name

        self.merchant = finance.Merchant(
            code="PKG-M-TEST0001",
            display_name="متجر الاختبار",
            legal_name="شركة الاختبار للتجارة",
            commercial_registration="1010101010",
            tax_number="310000000000003",
            contact_phone="0500000000",
            contact_email="merchant@example.test",
            iban="SA0000000000000000000000",
            bank_name="بنك الاختبار",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.application = onboarding.MerchantOnboardingApplication(
            merchant_id=self.merchant.id,
            status="documents",
            activity="تجارة التجزئة",
            national_address="الرياض",
            representative_name="ممثل المنشأة",
            representative_title="المدير العام",
        )
        self.db.add(self.application)
        self.db.flush()
        source_doc = onboarding.MerchantOnboardingDocument(
            application_id=self.application.id,
            merchant_id=self.merchant.id,
            original_name="commercial-registration.pdf",
            storage_key=f"{self.merchant.id}/commercial-registration.pdf",
            content_type="application/pdf",
            size_bytes=9,
            sha256="a" * 64,
        )
        self.db.add(source_doc)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()
        if self.old_root is None:
            os.environ.pop("MERCHANT_DOCUMENT_ROOT", None)
        else:
            os.environ["MERCHANT_DOCUMENT_ROOT"] = self.old_root

    def test_submit_moves_to_contract_ready_without_sadq(self):
        application, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        self.assertEqual(application.status, "contract_ready")
        self.assertEqual(contract.status, "contract_ready")
        self.assertEqual(self.merchant.status, "pending")

    def test_contract_data_comes_from_saved_merchant_profile(self):
        _, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        data = manual.contract_data_for(self.merchant, self.application, contract)
        self.assertEqual(data.agreement_number, contract.agreement_number)
        self.assertEqual(data.legal_name, "شركة الاختبار للتجارة")
        self.assertEqual(data.commercial_registration, "1010101010")
        self.assertEqual(data.representative_name, "ممثل المنشأة")

    def test_merchant_signed_pdf_moves_application_to_review_but_not_active(self):
        _, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        stored = manual.store_merchant_signed_pdf(
            self.db,
            self.merchant,
            self.application,
            contract,
            filename="signed.pdf",
            content=b"%PDF-1.4 merchant signed",
        )
        self.assertEqual(stored.content_type, "application/pdf")
        self.assertTrue(stored.original_name.startswith("merchant-signed-"))
        self.assertEqual(contract.status, "merchant_signed")
        self.assertEqual(self.application.status, "pending_review")
        self.assertEqual(self.merchant.status, "pending")
        self.assertTrue((Path(self.tempdir.name) / stored.storage_key).is_file())

    def test_merchant_signed_upload_rejects_non_pdf(self):
        _, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        with self.assertRaises(ValueError):
            manual.store_merchant_signed_pdf(
                self.db,
                self.merchant,
                self.application,
                contract,
                filename="signed.txt",
                content=b"not a pdf",
            )

    def test_final_pdf_does_not_activate_until_explicit_approval(self):
        _, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        manual.store_merchant_signed_pdf(
            self.db,
            self.merchant,
            self.application,
            contract,
            filename="signed.pdf",
            content=b"%PDF-1.4 merchant signed",
        )
        final_doc = manual.store_pakgat_final_pdf(
            self.db,
            self.merchant,
            self.application,
            contract,
            filename="final.pdf",
            content=b"%PDF-1.4 jointly signed",
        )
        self.assertTrue(final_doc.original_name.startswith("final-signed-"))
        self.assertEqual(contract.status, "signed")
        self.assertEqual(self.application.status, "pending_review")
        self.assertEqual(self.merchant.status, "pending")

    def test_latest_contract_document_prefers_newest_matching_kind(self):
        _, contract = onboarding.submit_onboarding(
            self.db,
            self.merchant,
            declaration_accepted=True,
        )
        first = manual.store_merchant_signed_pdf(
            self.db, self.merchant, self.application, contract,
            filename="first.pdf", content=b"%PDF-1.4 first"
        )
        second = manual.store_merchant_signed_pdf(
            self.db, self.merchant, self.application, contract,
            filename="second.pdf", content=b"%PDF-1.4 second"
        )
        latest = manual.latest_contract_document(
            self.db, self.application.id, manual.MERCHANT_SIGNED_PREFIX
        )
        self.assertEqual(latest.id, second.id)
        self.assertNotEqual(first.id, second.id)


if __name__ == "__main__":
    unittest.main()
