import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import application as core
from app.jood_company_ops import CompanyContact
from app.jood_whatsapp_campaign import (
    JoodWhatsAppCampaign,
    JoodWhatsAppDispatch,
    campaign_contact_allowed,
    queue_campaign_contacts,
    mark_latest_dispatch_replied,
    requeue_failed_dispatches,
)


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


if __name__ == "__main__":
    unittest.main()
