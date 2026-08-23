import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import application as core

from app.jood_catalog import (
    CatalogItem,
    catalog_from_presented_options,
    execute_catalog_action,
    enforce_sales_action,
    is_sales_consent,
    load_live_catalog,
    parse_salla_catalog,
    strict_product_message,
)


class JoodCatalogTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            CatalogItem("11", "بكج هدية عناية", "https://pakgat.com/ar/p/11", 99.0),
            CatalogItem("22", "كوبون غسيل سيارة", "https://pakgat.com/ar/p/22", 17.25),
            CatalogItem("33", "بكج مطعم فاخر", "https://pakgat.com/ar/p/33", 120.0),
        ]

    def test_parses_real_salla_product_shape(self):
        payload = {"data": [{"id": 11, "name": "بكج هدية", "price": {"amount": 99}, "urls": {"customer": "https://pakgat.com/ar/p/11"}}]}
        self.assertEqual(parse_salla_catalog(payload), [self.items[0]._replace(name="بكج هدية")])

    def test_send_catalog_options_executes_with_real_links(self):
        decision = {"action": "send_catalog_options", "selected_option": "هدايا", "reply": "هذه خيارات مناسبة:"}
        result = execute_catalog_action(decision, self.items)
        self.assertIn("بكج هدية عناية", result.reply)
        self.assertIn("https://pakgat.com/ar/p/11", result.reply)
        self.assertEqual(result.presented_options[0]["id"], "11")

    def test_executor_keeps_one_canonical_product_url_at_message_end(self):
        decision = {
            "action": "send_product_link",
            "selected_option": "هدايا",
            "reply": "هذا العرض مناسب لك https://pakgat.com/ar/p/11 وتقدر تستخدم كود VIP",
        }
        result = execute_catalog_action(decision, self.items)
        self.assertEqual(result.reply.count("https://pakgat.com/ar/p/11"), 1)
        self.assertEqual(result.reply, strict_product_message(self.items[0]))

    def test_product_action_falls_back_to_featured_item_when_selection_is_unknown(self):
        decision = {
            "action": "send_product_link",
            "selected_option": "اختيار غير مطابق",
            "reply": "هذا هو العرض المقترح لك.",
        }
        result = execute_catalog_action(decision, self.items)
        self.assertEqual(result.reply, strict_product_message(self.items[0]))

    def test_arabic_sales_consent_is_detected_without_ai_guessing(self):
        for text in ("ارسل", "أرسل", "موافق", "تمام", "تفضل", "ايه ارسل"):
            self.assertTrue(is_sales_consent(text), text)
        self.assertFalse(is_sales_consent("لا ترسل"))

    def test_backend_replaces_hallucinated_offer_with_real_catalog_product(self):
        decision = {
            "action": "send_product_link",
            "selected_option": "11",
            "reply": "عرض ليلة في فندق فاخر مع إفطار لشخصين.",
        }
        result = execute_catalog_action(decision, self.items)
        self.assertNotIn("فندق", result.reply)
        self.assertNotIn("إفطار", result.reply)
        self.assertIn(self.items[0].name, result.reply)
        self.assertIn("VIP", result.reply)

    def test_strict_product_template_is_exact_and_contains_only_catalog_fields(self):
        product = self.items[0]
        self.assertEqual(
            strict_product_message(product),
            "بدون قروشة.. أهلاً بك في باكيجات! 🌸\n\n"
            "أبشر بعزك، هذا رابط العرض المباشر لـ بكج هدية عناية:\n"
            "🔗 https://pakgat.com/ar/p/11\n\n"
            "خصمك يضبطك مع كود: VIP 🚀",
        )

    def test_every_product_action_uses_the_same_strict_template(self):
        for action in ("pitch_product", "send_product_link", "send_selected_option"):
            decision = {
                "action": action,
                "selected_option": "1" if action == "send_selected_option" else "11",
                "reply": "نص من النموذج يجب حذفه بالكامل.",
            }
            result = execute_catalog_action(
                decision,
                self.items,
                previous_options=[{"id": "11"}],
            )
            self.assertEqual(result.reply, strict_product_message(self.items[0]))

    def test_consent_forces_previous_product_link_and_fulfills_commitment(self):
        model_decision = {
            "action": "answer",
            "reply": "هل تحب أرسل العرض؟",
            "last_commitment_fulfilled": False,
        }
        state = {"selected_product_id": "11", "presented_options": [{"id": "11"}]}
        decision = enforce_sales_action(model_decision, "ارسل", state)
        self.assertEqual(decision["action"], "send_product_link")
        self.assertEqual(decision["selected_option"], "11")
        self.assertTrue(decision["last_commitment_fulfilled"])

    def test_saved_real_product_is_available_when_salla_temporarily_fails(self):
        options = [{"id": "11", "name": "بكج هدية عناية", "url": "https://pakgat.com/ar/p/11"}]
        self.assertEqual(catalog_from_presented_options(options), [self.items[0]._replace(price=0)])

    def test_selecting_second_option_uses_saved_option_not_literal_guessing(self):
        decision = {"action": "send_selected_option", "selected_option": "2", "reply": "اختيار ممتاز."}
        previous = [{"id": "11", "name": "هدية", "url": "https://pakgat.com/ar/p/11"}, {"id": "22", "name": "سيارات", "url": "https://pakgat.com/ar/p/22"}]
        result = execute_catalog_action(decision, self.items, previous_options=previous)
        self.assertIn("https://pakgat.com/ar/p/11", result.reply)

    def test_empty_product_list_falls_back_to_known_order_product_details(self):
        class FakeScalars:
            def all(self):
                return ["11"]

        class FakeResult:
            def scalars(self):
                return FakeScalars()

        class FakeDB:
            def execute(self, _statement):
                return FakeResult()

        credential = type("Credential", (), {"merchant_id": "650097422"})()
        responses = [
            ({"data": []}, None),
            ({"data": {"id": 11, "name": "بكج هدية", "price": {"amount": 99}, "urls": {"customer": "https://pakgat.com/ar/p/11"}}}, None),
        ]
        with patch("app.jood_catalog.core.latest_salla_credential", return_value=credential), patch(
            "app.jood_catalog.core.fetch_salla_json_endpoint", side_effect=responses
        ):
            items = load_live_catalog(FakeDB())
        self.assertEqual(items[0].name, "بكج هدية")

    def test_catalog_retries_once_after_transient_salla_error(self):
        credential = type("Credential", (), {"merchant_id": "650097422"})()
        success = {
            "data": [{"id": 11, "name": "بكج هدية", "price": {"amount": 99}, "urls": {"customer": "https://pakgat.com/ar/p/11"}}]
        }
        with patch("app.jood_catalog.core.latest_salla_credential", return_value=credential), patch(
            "app.jood_catalog.core.fetch_salla_json_endpoint",
            side_effect=[(None, "temporary"), (success, None)],
        ):
            items = load_live_catalog(object())
        self.assertEqual(items[0].id, "11")

    def test_successful_catalog_is_persisted_and_used_during_api_outage(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        core.Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        credential = type("Credential", (), {"merchant_id": "650097422"})()
        success = {
            "data": [{"id": 11, "name": "بكج هدية", "price": {"amount": 99}, "urls": {"customer": "https://pakgat.com/ar/p/11"}}]
        }
        try:
            with patch("app.jood_catalog.core.latest_salla_credential", return_value=credential), patch(
                "app.jood_catalog.core.fetch_salla_json_endpoint", return_value=(success, None)
            ):
                first = load_live_catalog(db)
            with patch("app.jood_catalog.core.latest_salla_credential", return_value=credential), patch(
                "app.jood_catalog.core.fetch_salla_json_endpoint", return_value=(None, "temporary")
            ):
                cached = load_live_catalog(db)
            self.assertEqual(cached, first)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
