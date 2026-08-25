import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app.customer_notifications import (
    customer_details_received_reply,
    customer_response_reply,
    resolve_customer_response,
)
from app.jood_company_ops import CompanyContact, JoodHandoff, capture_open_handoff_message


class CustomerNotificationResponseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (core.Voucher.__table__, core.CustomerNotification.__table__, CompanyContact.__table__, JoodHandoff.__table__):
            table.create(self.engine)
        self.db = Session(self.engine)
        self.contact = CompanyContact(phone="966500000000", contact_type="customer")
        self.db.add(self.contact)
        self.db.commit()
        self.voucher = core.create_voucher_record(
            self.db, "o:p:1", "p", "عرض", "شريك", "عميل", "0500000000", None
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _prompt(self, kind):
        row = core.ensure_customer_notification(self.db, self.voucher, kind, "message")
        row.status = "sent"
        row.sent_at = core.now_utc()
        self.db.commit()
        return row

    def test_receipt_and_support_responses_require_an_open_prompt(self):
        self.assertIsNone(resolve_customer_response(self.db, "966500000000", "1", self.contact.id))
        receipt = self._prompt("voucher_issued")
        result = resolve_customer_response(self.db, "966500000000", "1", self.contact.id)
        self.assertEqual(result.action, "receipt_confirmed")
        self.db.refresh(receipt)
        self.assertEqual(receipt.response_value, "1")

        second_voucher = core.create_voucher_record(
            self.db, "o:p:2", "p", "عرض", "شريك", "عميل", "0500000000", None
        )
        support = core.ensure_customer_notification(self.db, second_voucher, "voucher_issued", "message")
        support.status = "sent"
        self.db.commit()
        result = resolve_customer_response(self.db, "966500000000", "2", self.contact.id)
        self.assertEqual(result.action, "human_handoff")
        self.assertEqual(len(self.db.scalars(select(JoodHandoff)).all()), 1)
        self.assertIsNone(resolve_customer_response(self.db, "966500000000", "2", self.contact.id))
        self.assertEqual(len(self.db.scalars(select(JoodHandoff)).all()), 1)

    def test_merchant_numeric_reply_is_not_consumed_by_customer_notification_prompt(self):
        prompt = self._prompt("voucher_issued")
        result = resolve_customer_response(
            self.db,
            "966500000000",
            "1",
            self.contact.id,
            contact_type="merchant",
        )
        self.assertIsNone(result)
        self.db.refresh(prompt)
        self.assertIsNone(prompt.response_value)

    def test_latest_redemption_prompt_takes_precedence_for_rating(self):
        self._prompt("voucher_issued")
        rating = core.ensure_customer_notification(self.db, self.voucher, "voucher_redeemed", "message")
        rating.status = "sent"
        rating.sent_at = core.now_utc()
        self.db.commit()
        result = resolve_customer_response(self.db, "966500000000", "2", self.contact.id)
        self.assertEqual(result.action, "rating_recorded")
        self.assertEqual(result.value, "2")
        self.assertEqual(len(self.db.scalars(select(JoodHandoff)).all()), 0)

    def test_invalid_rating_remains_for_normal_routing(self):
        self._prompt("voucher_redeemed")
        self.assertIsNone(resolve_customer_response(self.db, "966500000000", "6", self.contact.id))

    def test_only_support_request_gets_an_immediate_acknowledgement(self):
        self.assertIsNone(customer_response_reply("receipt_confirmed"))
        self.assertIsNone(customer_response_reply("rating_recorded"))
        self.assertEqual(
            customer_response_reply("human_handoff"),
            "*العلم غانم ومجمّلك! أبشر بسعدك، وما يصير خاطرك إلا طيب.*\n\n"
            "عشان نخدمك عالسريع وبدون تأخير، اكتب استفسارك أو المشكلة اللي تواجهك بمسج واحد، "
            "وبإذن الله توصل طوالي لخدمة العملاء ويضبطونك.",
        )
        self.assertEqual(
            customer_details_received_reply(),
            "*وصلنا علمك يا بعدي ✅*\n\n"
            "أبشر بسعدك، تم رفع المشكلة لخدمة العملاء، وبيردون عليك بأسرع وقت ويضبطونك. خليك قريب!",
        )

    def test_first_message_after_support_choice_becomes_handoff_details(self):
        handoff = JoodHandoff(
            contact_id=self.contact.id,
            kind="customer_support",
            status="open",
            details="awaiting_customer_details",
        )
        self.db.add(handoff)
        self.db.commit()

        captured = capture_open_handoff_message(
            self.db,
            self.contact.id,
            "لم أستطع فتح رابط القسيمة",
        )

        self.assertTrue(captured)
        self.db.refresh(handoff)
        self.assertEqual(handoff.details, "لم أستطع فتح رابط القسيمة")
        self.assertFalse(
            capture_open_handoff_message(self.db, self.contact.id, "رسالة إضافية")
        )


if __name__ == "__main__":
    unittest.main()
