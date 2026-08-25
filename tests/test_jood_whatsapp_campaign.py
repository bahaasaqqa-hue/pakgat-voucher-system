import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import application as core
from app.jood_company_ops import CompanyContact
from app import jood_whatsapp_campaign as campaign_module
from app.jood_outbound import ensure_outbound_opening
from app.jood_whatsapp_campaign import (
    JoodWhatsAppCampaign,
    JoodWhatsAppDispatch,
    campaign_contact_allowed,
    queue_campaign_contacts,
    mark_latest_dispatch_replied,
    requeue_failed_dispatches,
)


RIYADH = ZoneInfo("Asia/Riyadh")


class JoodWhatsAppCampaignTests(unittest.TestCase):
    def test_customer_campaign_targets_only_active_customers(self):
        customer = SimpleNamespace(contact_type="customer", status="active")
        merchant = SimpleNamespace(contact_type="merchant", status="active")
        blocked = SimpleNamespace(contact_type="customer", status="do_not_contact")
        self.assertTrue(campaign_contact_allowed(customer, "customer"))
        self.assertFalse(campaign_contact_allowed(merchant, "customer"))
        self.assertFalse(campaign_contact_allowed(blocked, "customer"))

    def test_merchant_campaign_targets_only_active_merchants(self):
        merchant = SimpleNamespace(contact_type="merchant", status="active")
        customer = SimpleNamespace(contact_type="customer", status="active")
        self.assertTrue(campaign_contact_allowed(merchant, "merchant"))
        self.assertFalse(campaign_contact_allowed(customer, "merchant"))

    def test_queue_campaign_contacts_excludes_wrong_type_and_do_not_contact_and_is_idempotent(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            active = CompanyContact(phone="966501111111", contact_type="merchant", status="active")
            blocked = CompanyContact(phone="966502222222", contact_type="merchant", status="do_not_contact")
            customer = CompanyContact(phone="966503333333", contact_type="customer", status="active")
            campaign = JoodWhatsAppCampaign(name="تجار", contact_type="merchant", goal="", status="active")
            db.add_all([active, blocked, customer, campaign])
            db.commit()

            self.assertEqual(queue_campaign_contacts(db, campaign), 1)
            self.assertEqual(queue_campaign_contacts(db, campaign), 0)
            rows = list(db.scalars(select(JoodWhatsAppDispatch)).all())
            self.assertEqual([(row.contact_id, row.status) for row in rows], [(active.id, "queued")])

    def test_inbound_reply_marks_latest_sent_dispatch_replied(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            contact = CompanyContact(phone="966501111111", contact_type="customer", status="active")
            campaign = JoodWhatsAppCampaign(name="عملاء", contact_type="customer", goal="", status="active")
            db.add_all([contact, campaign])
            db.commit()
            dispatch = JoodWhatsAppDispatch(
                campaign_id=campaign.id,
                contact_id=contact.id,
                message="مرحبًا",
                status="sent",
                provider_status="HTTP 200",
            )
            db.add(dispatch)
            db.commit()

            self.assertTrue(mark_latest_dispatch_replied(db, contact.id))
            self.assertEqual(dispatch.status, "replied")
            self.assertFalse(mark_latest_dispatch_replied(db, contact.id))

    def test_retry_requeues_only_failed_dispatches(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            contact_a = CompanyContact(phone="966501111111", contact_type="customer", status="active")
            contact_b = CompanyContact(phone="966502222222", contact_type="customer", status="active")
            campaign = JoodWhatsAppCampaign(name="عملاء", contact_type="customer", goal="", status="completed")
            db.add_all([contact_a, contact_b, campaign])
            db.commit()
            failed = JoodWhatsAppDispatch(campaign_id=campaign.id, contact_id=contact_a.id, message="", status="failed")
            sent = JoodWhatsAppDispatch(campaign_id=campaign.id, contact_id=contact_b.id, message="تم", status="sent")
            db.add_all([failed, sent])
            db.commit()

            self.assertEqual(requeue_failed_dispatches(db, campaign), 1)
            self.assertEqual(failed.status, "queued")
            self.assertEqual(sent.status, "sent")
            self.assertEqual(campaign.status, "active")

    def test_campaign_send_interval_is_ten_minutes(self):
        self.assertEqual(
            getattr(campaign_module, "CAMPAIGN_SEND_INTERVAL_SECONDS", None),
            600,
        )

    def test_campaign_send_window_is_09_to_22_riyadh(self):
        predicate = getattr(campaign_module, "campaign_send_window_open", None)
        self.assertTrue(callable(predicate), "campaign_send_window_open must exist")
        self.assertFalse(predicate(datetime(2026, 8, 25, 8, 59, tzinfo=RIYADH)))
        self.assertTrue(predicate(datetime(2026, 8, 25, 9, 0, tzinfo=RIYADH)))
        self.assertTrue(predicate(datetime(2026, 8, 25, 21, 59, 59, tzinfo=RIYADH)))
        self.assertFalse(predicate(datetime(2026, 8, 25, 22, 0, tzinfo=RIYADH)))

    def test_campaign_wait_until_next_window_uses_riyadh_time(self):
        waiter = getattr(campaign_module, "campaign_seconds_until_send_window", None)
        self.assertTrue(callable(waiter), "campaign_seconds_until_send_window must exist")
        self.assertEqual(waiter(datetime(2026, 8, 25, 8, 50, tzinfo=RIYADH)), 600)
        self.assertEqual(waiter(datetime(2026, 8, 25, 22, 0, tzinfo=RIYADH)), 39600)

    def test_merchant_first_touch_always_includes_official_site(self):
        contact = SimpleNamespace(display_name="صالون اختبار", business_name="سبا")
        message = ensure_outbound_opening(
            "أهلًا صالون اختبار، معك جود من منصة باكيجات. أتواصل معك لعرض فرصة تعاون لنشاط سبا تساعدكم في الوصول لعملاء جدد عبر عروض وبكجات مميزة.",
            "merchant",
            contact,
        )
        self.assertIn("https://pakgat.com/ar", message)
        self.assertEqual(message.count("https://pakgat.com/ar"), 1)


if __name__ == "__main__":
    unittest.main()
