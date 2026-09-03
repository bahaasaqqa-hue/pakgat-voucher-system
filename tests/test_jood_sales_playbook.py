import unittest
from types import SimpleNamespace

from app.jood_catalog import CatalogItem
from app.jood_sales_playbook import SALES_FACTS, featured_product_context, sales_opening_fallback


class JoodSalesPlaybookTests(unittest.TestCase):
    def test_playbook_contains_approved_sales_facts(self):
        for fact in ("تمارا", "VIP", "5%", "كاش باك", "التغليف", "التوصيل", "تغيير الجو"):
            self.assertIn(fact, SALES_FACTS)

    def test_opening_pitches_real_product_before_question(self):
        product = CatalogItem("1", "بكج تجربة ترفيهية", "https://pakgat.com/ar/p/1", 99)
        reply = sales_opening_fallback(SimpleNamespace(display_name="بهاء"), product)
        self.assertIn(product.name, reply)
        self.assertIn("99", reply)
        self.assertIn("تمارا", reply)
        self.assertIn("VIP", reply)
        self.assertNotIn("أي فئة", reply)
        self.assertLess(reply.index(product.name), reply.index("تحب"))

    def test_featured_context_forbids_category_first_interview(self):
        product = CatalogItem("1", "عرض فعلي", "https://pakgat.com/ar/p/1", 50)
        context = featured_product_context(product)
        self.assertIn("ابدئي بهذا المنتج تحديدًا", context)
        self.assertIn(product.url, context)


if __name__ == "__main__":
    unittest.main()
