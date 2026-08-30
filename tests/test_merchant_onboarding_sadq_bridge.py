import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_onboarding_sadq_bridge as bridge  # noqa: F401


class MerchantOnboardingSadqBridgeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        finance.Merchant.__table__.create(self.engine)
        finance.MerchantContract.__table__.create(self.engine)
        onboarding.MerchantOnboardingApplication.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-SADQ-BRIDGE",
            display_name="تام العاصمة",
            contact_phone="966504161514",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.application = onboarding.MerchantOnboardingApplication(
            merchant_id=self.merchant.id,
            status="sadq_pending",
        )
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0201",
            status="sadq_pending",
            sadq_document_id="sadq-doc-201",
            sadq_transaction_id="sadq-env-201",
        )
        self.db.add_all([self.application, self.contract])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_signed_transition_moves_application_to_pending_review_without_activation(self):
        self.contract.status = "signed"
        self.db.commit()
        self.db.refresh(self.application)
        self.db.refresh(self.merchant)
        self.assertEqual(self.application.status, "pending_review")
        self.assertEqual(self.merchant.status, "pending")

    def test_unrelated_contract_update_does_not_advance_application(self):
        self.contract.sadq_document_id = "sadq-doc-updated"
        self.db.commit()
        self.db.refresh(self.application)
        self.assertEqual(self.application.status, "sadq_pending")

    def test_rejected_application_is_not_reopened_by_late_signed_event(self):
        self.application.status = "rejected"
        self.merchant.status = "rejected"
        self.db.commit()
        self.contract.status = "signed"
        self.db.commit()
        self.db.refresh(self.application)
        self.db.refresh(self.merchant)
        self.assertEqual(self.application.status, "rejected")
        self.assertEqual(self.merchant.status, "rejected")


if __name__ == "__main__":
    unittest.main()
