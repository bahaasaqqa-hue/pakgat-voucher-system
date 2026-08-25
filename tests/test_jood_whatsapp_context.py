import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import application as core
import app.jood_whatsapp_context as whatsapp_context
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
        options = [{"id": "11", "name": "عرض أول", "url": "https://pakgat.com/ar/p/11"}]
        row = remember_outreach_context(
            self.db,
            7,
            "customer",
            "تعريف العميل بالعروض",
            "individual",
            presented_options=options,
        )
        self.assertEqual(row.state_json["direction"], "outbound")
        self.assertEqual(row.state_json["persona"], "outbound_customer_sales")
        self.assertEqual(row.state_json["selected_product_id"], "11")
        update_outreach_state(
            self.db,
            7,
            next_stage="details_shared",
            last_commitment="سؤال العميل عن الفئة المفضلة",
            collected_info={"interest": "car_care"},
            presented_options=options,
            selected_product_id="11",
            status="active",
        )
        self.assertEqual(row.state_json["current_stage"], "details_shared")
        self.assertEqual(row.state_json["collected_info"]["interest"], "car_care")
        self.assertEqual(row.state_json["presented_options"], options)
        self.assertEqual(row.state_json["selected_product_id"], "11")

    def test_campaign_choice_one_returns_approved_sales_handoff_action(self):
        row = remember_outreach_context(
            self.db,
            7,
            "merchant",
            "استقطاب التاجر إلى بكجات",
            "campaign",
        )
        resolver = getattr(whatsapp_context, "merchant_campaign_choice_action", None)
        self.assertIsNotNone(resolver, "merchant campaign choice resolver is missing")

        action = resolver("1", "merchant", row)

        self.assertIsNotNone(action)
        self.assertEqual(action.handoff_kind, "merchant_partnership")
        self.assertEqual(action.next_stage, "handed_off")
        self.assertIn("*أبشروا بالسعد 🙌*", action.reply)
        self.assertIn("*حملة تسويق ومبيعات متكاملة*", action.reply)
        self.assertIn("*بدون أي رسوم أو تكاليف مسبقة*", action.reply)
        self.assertIn("قسيمة رقمية (QR)", action.reply)
        self.assertIn("تمسحونها بجوالكم خلال ثوانٍ", action.reply)
        self.assertIn("*مسؤول الشراكات في بكجات*", action.reply)
        self.assertIn("بعقد رسمي وموثق يحفظ حقوق الجميع", action.reply)
        self.assertNotIn("أرسلوا لنا", action.reply)

    def test_campaign_choice_action_does_not_hijack_question_or_inbound_merchant(self):
        resolver = getattr(whatsapp_context, "merchant_campaign_choice_action", None)
        self.assertIsNotNone(resolver, "merchant campaign choice resolver is missing")

        campaign_row = remember_outreach_context(
            self.db,
            7,
            "merchant",
            "استقطاب التاجر إلى بكجات",
            "campaign",
        )
        self.assertIsNone(resolver("2", "merchant", campaign_row))

        inbound_row = remember_outreach_context(
            self.db,
            8,
            "merchant",
            "محادثة فردية",
            "individual",
        )
        self.assertIsNone(resolver("1", "merchant", inbound_row))
        self.assertIsNone(resolver("1", "customer", campaign_row))


if __name__ == "__main__":
    unittest.main()
