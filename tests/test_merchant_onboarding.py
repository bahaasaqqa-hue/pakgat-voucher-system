import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding


class MerchantOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        finance.Merchant.__table__.create(self.engine)
        finance.MerchantContract.__table__.create(self.engine)
        contracts.MerchantContractApproval.__table__.create(self.engine)
        onboarding.MerchantRegistrationOtpChallenge.__table__.create(self.engine)
        onboarding.MerchantOnboardingApplication.__table__.create(self.engine)
        onboarding.MerchantOnboardingDocument.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_routes_cover_registration_profile_documents_and_submit(self):
        paths = {(getattr(route, "path", ""), method) for route in core.app.routes for method in (getattr(route, "methods", set()) or set())}
        expected = {
            ("/merchant/register", "GET"),
            ("/merchant/register/request", "POST"),
            ("/merchant/register/verify", "POST"),
            ("/merchant/onboarding", "GET"),
            ("/merchant/onboarding/profile", "POST"),
            ("/merchant/onboarding/documents", "POST"),
            ("/merchant/onboarding/submit", "POST"),
        }
        self.assertTrue(expected.issubset(paths))

    def test_unknown_phone_can_verify_before_merchant_is_created(self):
        with patch.object(onboarding.secrets, "randbelow", return_value=123456), patch.object(onboarding, "_send_whatsloop_text", return_value=(True, "HTTP 200")) as send:
            token, delivered = onboarding.request_registration_otp(self.db, "0504161514")
        self.assertTrue(delivered)
        self.assertTrue(token)
        self.assertEqual(self.db.query(finance.Merchant).count(), 0)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "966504161514")
        self.assertIn("123456", send.call_args.args[1])
        challenge = self.db.query(onboarding.MerchantRegistrationOtpChallenge).one()
        self.assertNotEqual(challenge.otp_hash, "123456")
        self.assertEqual(challenge.destination, "966504161514")
        merchant_id = onboarding.verify_registration_otp(self.db, token, "123456")
        merchant = self.db.get(finance.Merchant, merchant_id)
        self.assertEqual(merchant.status, "pending")
        self.assertEqual(merchant.contact_phone, "966504161514")
        application = self.db.scalar(select(onboarding.MerchantOnboardingApplication).where(onboarding.MerchantOnboardingApplication.merchant_id == merchant.id))
        self.assertEqual(application.status, "profile")

    def test_registration_resend_cooldown_does_not_send_twice(self):
        with patch.object(onboarding.secrets, "randbelow", return_value=123456), patch.object(onboarding, "_send_whatsloop_text", return_value=(True, "HTTP 200")) as send:
            first, first_delivered = onboarding.request_registration_otp(self.db, "0555555555")
            second, second_delivered = onboarding.request_registration_otp(self.db, "0555555555")
        self.assertTrue(first_delivered)
        self.assertFalse(second_delivered)
        self.assertEqual(first, second)
        send.assert_called_once()

    def _registered_merchant(self):
        with patch.object(onboarding.secrets, "randbelow", return_value=123456), patch.object(onboarding, "_send_whatsloop_text", return_value=(True, "HTTP 200")):
            token, _ = onboarding.request_registration_otp(self.db, "0504161514")
        merchant_id = onboarding.verify_registration_otp(self.db, token, "123456")
        return self.db.get(finance.Merchant, merchant_id)

    def test_profile_collects_contract_fields_and_keeps_phone_verified(self):
        merchant = self._registered_merchant()
        application = onboarding.save_onboarding_profile(
            self.db, merchant,
            display_name="تام العاصمة", legal_name="تام العاصمة للتجارة", commercial_registration="1010101010",
            activity="مطاعم ومقاهي", tax_number="310000000000003", bank_name="البنك الأهلي السعودي",
            iban="SA0000000000000000000000", national_address="الرياض - المملكة العربية السعودية",
            contact_email="merchant@example.com", website="https://merchant.example.com",
            representative_name="أحمد محمد", representative_title="المدير العام",
        )
        self.db.refresh(merchant)
        self.assertEqual(merchant.display_name, "تام العاصمة")
        self.assertEqual(merchant.legal_name, "تام العاصمة للتجارة")
        self.assertEqual(merchant.commercial_registration, "1010101010")
        self.assertEqual(merchant.tax_number, "310000000000003")
        self.assertEqual(merchant.bank_name, "البنك الأهلي السعودي")
        self.assertEqual(merchant.iban, "SA0000000000000000000000")
        self.assertEqual(merchant.contact_email, "merchant@example.com")
        self.assertEqual(merchant.contact_phone, "966504161514")
        self.assertEqual(application.activity, "مطاعم ومقاهي")
        self.assertEqual(application.national_address, "الرياض - المملكة العربية السعودية")
        self.assertEqual(application.representative_name, "أحمد محمد")
        self.assertEqual(application.representative_title, "المدير العام")
        self.assertEqual(application.status, "documents")

    def test_documents_are_open_multi_upload_metadata_not_fixed_types(self):
        merchant = self._registered_merchant()
        with patch.dict(os.environ, {"MERCHANT_DOCUMENT_ROOT": self.tmp.name}):
            first = onboarding.store_onboarding_document(self.db, merchant, filename="السجل التجاري.pdf", content_type="application/pdf", content=b"%PDF-1.4 test")
            second = onboarding.store_onboarding_document(self.db, merchant, filename="شهادة-البنك.png", content_type="image/png", content=b"\x89PNG\r\n\x1a\nmock")
        self.assertEqual(self.db.query(onboarding.MerchantOnboardingDocument).count(), 2)
        self.assertEqual(first.original_name, "السجل التجاري.pdf")
        self.assertEqual(second.original_name, "شهادة-البنك.png")
        self.assertTrue((Path(self.tmp.name) / first.storage_key).is_file())
        self.assertTrue((Path(self.tmp.name) / second.storage_key).is_file())
        self.assertFalse(hasattr(first, "document_type"))

    def test_submit_requires_declaration_and_at_least_one_document(self):
        merchant = self._registered_merchant()
        onboarding.save_onboarding_profile(
            self.db, merchant,
            display_name="تام العاصمة", legal_name="تام العاصمة للتجارة", commercial_registration="1010101010",
            activity="مطاعم", tax_number="310000000000003", bank_name="الأهلي", iban="SA0000000000000000000000",
            national_address="الرياض", contact_email="merchant@example.com", website="", representative_name="أحمد", representative_title="مدير",
        )
        with self.assertRaises(ValueError): onboarding.submit_onboarding(self.db, merchant, declaration_accepted=False)
        with self.assertRaises(ValueError): onboarding.submit_onboarding(self.db, merchant, declaration_accepted=True)
        with patch.dict(os.environ, {"MERCHANT_DOCUMENT_ROOT": self.tmp.name}):
            onboarding.store_onboarding_document(self.db, merchant, filename="official.pdf", content_type="application/pdf", content=b"%PDF-1.4 test")
        application, contract = onboarding.submit_onboarding(self.db, merchant, declaration_accepted=True)
        self.assertEqual(application.status, "ready_for_sadq")
        self.assertIsNotNone(application.declaration_accepted_at)
        self.assertIsNotNone(application.submitted_at)
        self.assertEqual(contract.status, "ready_for_sadq")
        self.assertIsNotNone(contract.agreement_number)
        self.db.refresh(merchant)
        self.assertEqual(merchant.status, "pending")

    def test_sadq_signature_moves_application_to_pakgat_review_not_active(self):
        merchant = self._registered_merchant()
        application = self.db.scalar(select(onboarding.MerchantOnboardingApplication).where(onboarding.MerchantOnboardingApplication.merchant_id == merchant.id))
        contract = finance.MerchantContract(merchant_id=merchant.id, agreement_number="PKG-MA-2026-08-0999", status="sadq_pending", sadq_document_id="sadq-doc", sadq_transaction_id="sadq-env")
        self.db.add(contract); application.status = "sadq_pending"; self.db.commit()
        onboarding.mark_sadq_signed_for_review(self.db, contract)
        self.db.refresh(application); self.db.refresh(merchant)
        self.assertEqual(contract.status, "signed")
        self.assertEqual(application.status, "pending_review")
        self.assertEqual(merchant.status, "pending")

    def test_pakgat_can_approve_only_after_sadq_signed(self):
        merchant = self._registered_merchant()
        contract = finance.MerchantContract(merchant_id=merchant.id, agreement_number="PKG-MA-2026-08-1000", status="sadq_pending")
        self.db.add(contract); self.db.commit()
        with self.assertRaises(ValueError): onboarding.approve_signed_onboarding(self.db, contract)
        contract.status = "signed"; self.db.commit()
        approval = onboarding.approve_signed_onboarding(self.db, contract)
        self.db.refresh(merchant); self.db.refresh(contract)
        self.assertEqual(merchant.status, "active")
        self.assertEqual(contract.status, "approved")
        self.assertEqual(approval.pakgat_signer_name, "بهاء السقا")
        self.assertEqual(approval.pakgat_signer_title, "مدير تطوير الأعمال")
        self.assertEqual(approval.pakgat_signer_phone, "0504161514")

    def test_pakgat_can_request_changes_or_reject_without_activation(self):
        merchant = self._registered_merchant()
        application = self.db.scalar(select(onboarding.MerchantOnboardingApplication).where(onboarding.MerchantOnboardingApplication.merchant_id == merchant.id))
        onboarding.request_onboarding_changes(self.db, application, "أرفق شهادة الآيبان الحديثة")
        self.assertEqual(application.status, "changes_requested")
        self.assertIn("الآيبان", application.review_note)
        self.db.refresh(merchant); self.assertEqual(merchant.status, "pending")
        onboarding.reject_onboarding(self.db, application, "المستندات غير مطابقة")
        self.assertEqual(application.status, "rejected")
        self.db.refresh(merchant); self.assertEqual(merchant.status, "rejected")


if __name__ == "__main__": unittest.main()
