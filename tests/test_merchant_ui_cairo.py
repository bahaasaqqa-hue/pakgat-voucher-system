import importlib.util
import unittest


class MerchantUICairoTests(unittest.TestCase):
    def _polisher(self):
        spec = importlib.util.find_spec("app.merchant_ui_cairo")
        self.assertIsNotNone(spec, "merchant_ui_cairo presentation module is missing")
        module = __import__("app.merchant_ui_cairo", fromlist=["apply_merchant_ui_polish"])
        return module.apply_merchant_ui_polish

    def test_cairo_is_loaded_and_applied_to_admin_controls(self):
        polish = self._polisher()
        source = "<html><head></head><body data-unified-admin-theme='standard'><main>التجار</main></body></html>"
        rendered = polish(source, "/admin/merchants")
        self.assertIn("family=Cairo", rendered)
        self.assertIn("font-family:'Cairo'", rendered)
        self.assertIn("button,input,select,textarea", rendered)

    def test_merchant_finance_labels_are_arabic(self):
        polish = self._polisher()
        source = """<html><head></head><body data-unified-admin-theme='standard'>
        <main class='wrap'><h1>التجار</h1>
        <table><tr><th>Redeemed</th><th>Refunded</th><th>Expired</th></tr>
        <tr><td>active</td><td>draft</td><td>paid</td></tr></table>
        <p>Redemption Rate: 10% · Refund Rate: 2%</p>
        <p><strong>IBAN:</strong> SA00</p>
        <p>التسوية الأسبوعية الافتراضية يوم الخميس. لا يدخل هنا إلا ما تم Redeem فعليًا.</p>
        </main></body></html>"""
        rendered = polish(source, "/admin/merchants/1")
        for expected in ("مستخدمة", "مستردة", "منتهية", "نشط", "مسودة", "مدفوعة", "نسبة الاستبدال", "نسبة الاسترجاع", "الآيبان", "استبدال القسيمة فعليًا"):
            self.assertIn(expected, rendered)
        for forbidden in (">Redeemed<", ">Refunded<", ">Expired<", ">active<", ">draft<", ">paid<", "Redemption Rate:", "Refund Rate:", "<strong>IBAN:</strong>", "تم Redeem فعليًا"):
            self.assertNotIn(forbidden, rendered)

    def test_dashboard_lifecycle_labels_are_arabic(self):
        polish = self._polisher()
        source = "<html><head></head><body data-unified-admin-theme='standard'><div>Active / أموال معلقة</div><div>Redeemed</div><div>Expired بدون استخدام</div><div>Refunded</div><div>Cancelled / Revoked</div></body></html>"
        rendered = polish(source, "/admin")
        for expected in ("قسائم نشطة", "مستخدمة", "منتهية دون استخدام", "مستردة", "ملغاة"):
            self.assertIn(expected, rendered)
        for forbidden in ("Active / أموال معلقة", ">Redeemed<", "Expired بدون استخدام", ">Refunded<", "Cancelled / Revoked"):
            self.assertNotIn(forbidden, rendered)

    def test_non_admin_html_is_untouched(self):
        polish = self._polisher()
        source = "<html><head></head><body><p>Redeemed active</p></body></html>"
        self.assertEqual(polish(source, "/v/example"), source)


if __name__ == "__main__":
    unittest.main()
