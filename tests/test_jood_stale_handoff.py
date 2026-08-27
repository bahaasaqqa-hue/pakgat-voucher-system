import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import application as core
from app.jood_company_ops import CompanyContact, JoodHandoff
from app.jood_whatsapp_context import remember_outreach_context
import app.whatsloop_inbound as whatsloop_inbound


class JoodStaleHandoffTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.contact = CompanyContact(
            phone="966500000001",
            contact_type="merchant",
            business_name="Regression merchant",
            status="active",
            merchant_stage="handed_off",
        )
        self.db.add(self.contact)
        self.db.commit()
        self.db.refresh(self.contact)

    def tearDown(self):
        self.db.close()

    def _resolver(self):
        resolver = getattr(whatsloop_inbound, "open_handoff_blocks_current_outreach", None)
        self.assertIsNotNone(
            resolver,
            "inbound flow needs a stale-handoff gate that compares the open handoff with the current outreach",
        )
        return resolver

    def test_new_outreach_supersedes_older_open_handoff(self):
        now = datetime.now(timezone.utc)
        self.db.add(
            JoodHandoff(
                contact_id=self.contact.id,
                kind="merchant_partnership",
                status="open",
                details="old merchant handoff",
                created_at=now - timedelta(days=1),
            )
        )
        self.db.commit()

        context = remember_outreach_context(
            self.db,
            self.contact.id,
            "merchant",
            "new merchant outreach",
            "individual",
        )
        context.updated_at = now
        self.db.commit()

        self.assertFalse(self._resolver()(self.db, self.contact.id, context))

    def test_handoff_created_after_current_outreach_still_blocks_jood(self):
        now = datetime.now(timezone.utc)
        context = remember_outreach_context(
            self.db,
            self.contact.id,
            "merchant",
            "current merchant outreach",
            "individual",
        )
        context.updated_at = now - timedelta(minutes=5)
        self.db.commit()

        self.db.add(
            JoodHandoff(
                contact_id=self.contact.id,
                kind="merchant_partnership",
                status="open",
                details="new merchant handoff",
                created_at=now,
            )
        )
        self.db.commit()

        self.assertTrue(self._resolver()(self.db, self.contact.id, context))


if __name__ == "__main__":
    unittest.main()
