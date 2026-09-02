from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ADMIN_PASSWORD", "test-only-password")
os.environ.setdefault("ADMIN_SECRET", "test-only-admin-secret")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_manual_contract as manual
from app import merchant_contract_otp as otp
from app import merchant_contract_otp_compat  # noqa: F401 - stable fingerprint + safe audit lookup


class MerchantContractOtpTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-OTP0001",
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
            status="contract_ready",
            activity="تجارة التجزئة",
            national_address="الرياض",
            representative_name="ممثل المنشأة",
            representative_title="المدير العام",
        )
        self.db.add(self.application)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-09-0001",
            status="contract_ready",
        )
        self.db.add(self.contract)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_signature_otp_is_separate_and_bound_to_contract(self):
        sent = []
        with patch("app.merchant_contract_otp.secrets.randbelow", return_value=123456):
            challenge, delivered = otp.request_signature_otp(
                self.db,
                self.merchant,
                self.application,
                self.contract,
                sender=lambda phone, message: (sent.append((phone, message)) or True, "ok"),
            )
        self.assertTrue(delivered)
        self.assertEqual(challenge.status, "pending")
        self.assertEqual(challenge.agreement_number_snapshot, self.contract.agreement_number)
        self.assertTrue(challenge.contract_fingerprint)
        self.assertIn("PKG-MA-2026-09-0001", sent[0][1])

    def test_correct_signature_otp_moves_to_review_without_activation(self):
        with patch("app.merchant_contract_otp.secrets.randbelow", return_value=123456):
            otp.request_signature_otp(
                self.db,
                self.merchant,
                self.application,
                self.contract,
                sender=lambda phone, message: (True, "ok"),
            )
        accepted = otp.verify_signature_otp(
            self.db,
            self.merchant,
            self.application,
            self.contract,
            "123456",
            ip_address="127.0.0.1",
            user_agent="unit-test",
        )
        self.assertTrue(accepted)
        self.assertEqual(self.contract.status, "signed")
        self.assertEqual(self.application.status, "pending_review")
        self.assertEqual(self.merchant.status, "pending")
        latest = otp.latest_signature_challenge(self.db, self.contract.id)
        self.assertEqual(latest.status, "used")
        self.assertIsNotNone(latest.accepted_at)

    def test_wrong_signature_otp_does_not_sign_contract(self):
        with patch("app.merchant_contract_otp.secrets.randbelow", return_value=123456):
            otp.request_signature_otp(
                self.db,
                self.merchant,
                self.application,
                self.contract,
                sender=lambda phone, message: (True, "ok"),
            )
        accepted = otp.verify_signature_otp(
            self.db,
            self.merchant,
            self.application,
            self.contract,
            "999999",
        )
        self.assertFalse(accepted)
        self.assertEqual(self.contract.status, "contract_ready")
        self.assertEqual(self.application.status, "contract_ready")
        self.assertEqual(self.merchant.status, "pending")


if __name__ == "__main__":
    unittest.main()
