import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app.jood_company_ops import (
    CompanyContact,
    JoodHandoff,
    capture_open_handoff_message,
    has_open_handoff,
)
from app.jood_identity import should_jood_ai_reply
from app.jood_policy import sanitize_jood_reply


class MerchantInboundSafetyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        CompanyContact.__table__.create(self.engine)
        JoodHandoff.__table__.create(self.engine)
        self.db = Session(self.engine)

        self.contact = CompanyContact(
            phone="966500000001",
            contact_type="merchant",
            status="active",
            business_name="Test Merchant",
        )
        self.db.add(self.contact)
        self.db.commit()
        self.db.refresh(self.contact)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_customer_support_handoff_does_not_block_merchant_partnership_flow(self):
        self.db.add(
            JoodHandoff(
                contact_id=self.contact.id,
                kind="customer_support",
                status="open",
                details="old customer support request",
            )
        )
        self.db.commit()

        self.assertTrue(has_open_handoff(self.db, self.contact.id))
        self.assertTrue(
            has_open_handoff(self.db, self.contact.id, kind="customer_support")
        )
        self.assertFalse(
            has_open_handoff(self.db, self.contact.id, kind="merchant_partnership")
        )
        self.assertFalse(
            capture_open_handoff_message(
                self.db,
                self.contact.id,
                "1",
                kind="merchant_partnership",
            )
        )

    def test_strong_business_auto_reply_is_not_routed_to_jood(self):
        dermo = (
            "شكرا لك على تواصلك مع Dermo Bright. "
            "يرجى إخبارنا بما يمكننا القيام به لمساعدتك."
        )
        english = "Thank you for contacting Example Clinic. We have received your message."

        self.assertFalse(should_jood_ai_reply(dermo, "966575606000"))
        self.assertFalse(should_jood_ai_reply(english, "966575606001"))

        # Short greetings and campaign choices can be genuine human replies.
        self.assertTrue(should_jood_ai_reply("حياك الله", "966575606002"))
        self.assertTrue(should_jood_ai_reply("1", "966575606003"))

    def test_markdown_bold_pakgat_root_url_survives_sanitizer_exactly(self):
        message = "*معكم جود من منصة بكجات — https://pakgat.com*"
        safe = sanitize_jood_reply(
            message,
            approved_urls={"https://pakgat.com"},
        )

        self.assertEqual(safe, message)
        self.assertNotIn("https://pakgat.com/ar", safe)


if __name__ == "__main__":
    unittest.main()
