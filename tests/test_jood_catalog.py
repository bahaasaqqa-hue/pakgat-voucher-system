import unittest

from app.jood_catalog import CatalogItem, execute_catalog_action, parse_salla_catalog


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

    def test_selecting_second_option_uses_saved_option_not_literal_guessing(self):
        decision = {"action": "send_selected_option", "selected_option": "2", "reply": "اختيار ممتاز."}
        previous = [{"id": "11", "name": "هدية", "url": "https://pakgat.com/ar/p/11"}, {"id": "22", "name": "سيارات", "url": "https://pakgat.com/ar/p/22"}]
        result = execute_catalog_action(decision, self.items, previous_options=previous)
        self.assertIn("https://pakgat.com/ar/p/22", result.reply)


if __name__ == "__main__":
    unittest.main()
