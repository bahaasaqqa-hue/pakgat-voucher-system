import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import sadq_client


class FakeSadqClient:
    def __init__(self):
        self.envelopes = []
        self.invitations = []

    def initiate_base64_pdf(self, pdf_content, filename):
        self.envelopes.append((pdf_content, filename))
        return sadq_client.SadqEnvelope(document_id="doc-123", envelope_id="env-456")

    def send_nafath_invitation(self, document_id, **kwargs):
        self.invitations.append((document_id, kwargs))
        return sadq_client.SadqInvitation(
            invitation_url="https://pakgat-sandbox.sadq.sa/sign/invite-789"
        )


class MerchantOnboardingSadqStartTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        finance.Merchant.__table__.create(self.engine)
        finance.MerchantContract.__table__.create(self.engine)
        contracts.MerchantContractApproval.__table__.create(self.engine)
        onboarding.MerchantOnboardingApplication.__table__.create(self.engine)
        onboarding.MerchantOnboardingDocument.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-TEST",
            display_name="متجر الاختبار",
            legal_name="شركة الاختبار",
            commercial_registration="1010999999",
            tax_number="312000000000003",
            bank_name="البنك الأهلي السعودي",
            iban="SA1111111111111111111111",
            contact_phone="966500000000",
            contact_email="merchant@example.com",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.commit()
        self.application = onboarding.MerchantOnboardingApplication(
            merchant_id=self.merchant.id,
            status="ready_for_sadq",
            activity="تجهيز الهدايا",
            national_address="الرياض - المملكة العربية السعودية",
            website="https://merchant.example.com",
            representative_name="ممثل التاجر",
            representative_title="المدير العام",
            declaration_accepted_at=onboarding.core.now_utc(),
            submitted_at=onboarding.core.now_utc(),
        )
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0042",
            status="ready_for_sadq",
        )
        self.db.add_all([self.application, self.contract])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_start_sadq_signing_generates_real_pdf_saves_ids_and_returns_invitation(self):
        client = FakeSadqClient()
        rendered = []

        def fake_render(data):
            rendered.append(data)
            return b"%PDF-1.7\nreal-agreement\n"

        invitation_url = onboarding.start_sadq_signing(
            self.db,
            self.merchant,
            self.application,
            self.contract,
            client=client,
            render_pdf=fake_render,
        )

        self.assertEqual(invitation_url, "https://pakgat-sandbox.sadq.sa/sign/invite-789")
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0].agreement_number, "PKG-MA-2026-08-0042")
        self.assertEqual(rendered[0].legal_name, "شركة الاختبار")
        self.assertEqual(rendered[0].representative_name, "ممثل التاجر")
        self.assertEqual(client.envelopes[0][0], b"%PDF-1.7\nreal-agreement\n")
        self.assertEqual(client.envelopes[0][1], "PKG-MA-2026-08-0042.pdf")
        document_id, destination = client.invitations[0]
        self.assertEqual(document_id, "doc-123")
        self.assertEqual(destination["destination_name"], "ممثل التاجر")
        self.assertEqual(destination["destination_email"], "merchant@example.com")
        self.assertEqual(destination["destination_phone"], "+966500000000")
        self.assertEqual(destination["redirect_url"], "https://merchant.pakgat.com/merchant/onboarding")
        self.assertEqual(len(destination["available_to"]), 10)
        self.db.refresh(self.contract)
        self.db.refresh(self.application)
        self.assertEqual(self.contract.sadq_document_id, "doc-123")
        self.assertEqual(self.contract.sadq_transaction_id, "env-456")
        self.assertEqual(self.contract.status, "sadq_pending")
        self.assertEqual(self.application.status, "sadq_pending")

    def test_start_sadq_signing_reuses_existing_envelope_after_retry(self):
        self.contract.sadq_document_id = "doc-existing"
        self.contract.sadq_transaction_id = "env-existing"
        self.db.commit()
        client = FakeSadqClient()

        with patch.object(onboarding, "merchant_contract_pdf", create=True):
            invitation_url = onboarding.start_sadq_signing(
                self.db,
                self.merchant,
                self.application,
                self.contract,
                client=client,
                render_pdf=lambda _data: (_ for _ in ()).throw(AssertionError("PDF must not be regenerated")),
            )

        self.assertEqual(invitation_url, "https://pakgat-sandbox.sadq.sa/sign/invite-789")
        self.assertEqual(client.envelopes, [])
        self.assertEqual(client.invitations[0][0], "doc-existing")


if __name__ == "__main__":
    unittest.main()
