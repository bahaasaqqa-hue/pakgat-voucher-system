import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import application as core
from app.jood_whatsapp_context import (
    active_outreach_context,
    inbound_outreach_context,
    remember_outreach_context,
    update_outreach_state,
)


class JoodWhatsAppContextTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_remembers_latest_objective_for_contact(self):
        remember_outreach_context(self.db, 7, "customer", "عرّفيه بعروض السيارات", "individual")
        row = active_outreach_context(self.db, 7)
        self.assertEqual(row.mode, "customer")
        self.assertEqual(row.objective, "عرّفيه بعروض السيارات")

    def test_new_outreach_replaces_old_objective(self):
        remember_outreach_context(self.db, 7, "customer", "الهدف القديم", "individual")
        remember_outreach_context(self.db, 7, "merchant", "فرصة شراكة للمطعم", "campaign")
        row = active_outreach_context(self.db, 7)
        self.assertEqual(row.mode, "merchant")
        self.assertEqual(row.objective, "فرصة شراكة للمطعم")

    def test_inbound_context_explains_goal_without_prescribing_a_fixed_reply(self):
        remember_outreach_context(self.db, 7, "customer", "عرّفيه بعروض السيارات", "individual")
        context = inbound_outreach_context(self.db, 7)
        self.assertIn("outbound conversation", context.lower())
        self.assertIn("عرّفيه بعروض السيارات", context)
        self.assertIn("answer naturally", context.lower())
        self.assertNotIn("إذا قال موافق", context)

    def test_no_active_outreach_leaves_normal_inbound_flow_untouched(self):
        self.assertEqual(inbound_outreach_context(self.db, 999), "")

    def test_state_tracks_persona_stage_commitment_and_collected_info(self):
        row = remember_outreach_context(self.db, 7, "customer", "تعريف العميل بالعروض", "individual")
        self.assertEqual(row.state_json["direction"], "outbound")
        self.assertEqual(row.state_json["persona"], "outbound_customer_sales")
        update_outreach_state(
            self.db,
            7,
            next_stage="details_shared",
            last_commitment="سؤال العميل عن الفئة المفضلة",
            collected_info={"interest": "car_care"},
            status="active",
        )
        self.assertEqual(row.state_json["current_stage"], "details_shared")
        self.assertEqual(row.state_json["collected_info"]["interest"], "car_care")


if __name__ == "__main__":
    unittest.main()
