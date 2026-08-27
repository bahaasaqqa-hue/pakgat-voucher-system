import unittest

from app.merchant_ui_cairo import apply_merchant_ui_polish


STANDARD_SOURCE = """<html><head><title>Admin</title></head>
<body data-unified-admin-theme='standard'>
<div class='ua-shell'>
<aside class='ua-sidebar'>
<a class='ua-brand' href='/admin'><img src='/admin/theme/logo' alt='Pakgat'></a>
<nav class='ua-nav' aria-label='التنقل الإداري'>
<a data-nav-key='dashboard' class='ua-nav-link' href='/admin'>لوحة الإدارة</a>
<a data-nav-key='company' class='ua-nav-link' href='/admin/company'>شركة بكجات الذكية</a>
</nav>
</aside>
<section class='ua-workspace'><div class='ua-content'><h1>عنوان</h1><table><tr><th>رأس</th><td>قيمة</td></tr></table><button class='btn'>زر</button></div></section>
</div>
</body></html>"""


class AdminNavigationTypographyTests(unittest.TestCase):
    def test_standard_navigation_is_grouped_and_company_is_primary(self):
        rendered = apply_merchant_ui_polish(STANDARD_SOURCE, "/admin/merchants")

        for section in ("الرئيسية", "القسائم", "التجار والمالية", "التكاملات", "النظام"):
            self.assertIn(f">{section}<", rendered)

        expected_links = (
            ("company", "شركة بكجات الذكية", "/admin/company"),
            ("dashboard", "ملخص الإدارة", "/admin"),
            ("new_voucher", "قسيمة جديدة", "/admin/vouchers/new"),
            ("merchants", "التجار", "/admin/merchants"),
            ("settlements", "التسويات والمستحقات", "/admin/settlements"),
            ("partners", "بيانات الشركاء", "/admin/local-partners"),
            ("integrations", "تكامل سلة", "/admin/integrations"),
            ("audit", "سجل العمليات", "/admin/audit"),
        )
        for key, label, href in expected_links:
            self.assertIn(f"data-nav-key='{key}'", rendered)
            self.assertIn(f"href='{href}'", rendered)
            self.assertIn(label, rendered)

        self.assertLess(rendered.index("شركة بكجات الذكية"), rendered.index("ملخص الإدارة"))
        self.assertLess(rendered.index("التجار"), rendered.index("التسويات والمستحقات"))
        self.assertIn("data-nav-key='merchants' class='ua-nav-link active'", rendered)
        self.assertIn("class='ua-brand' href='/admin/company'", rendered)
        self.assertNotIn(">لوحة الإدارة<", rendered)

    def test_settlements_path_gets_active_navigation(self):
        rendered = apply_merchant_ui_polish(STANDARD_SOURCE, "/admin/settlements")
        self.assertIn("data-nav-key='settlements' class='ua-nav-link active'", rendered)
        self.assertNotIn("data-nav-key='merchants' class='ua-nav-link active'", rendered)

    def test_cairo_and_weight_hierarchy_apply_to_standard_admin(self):
        rendered = apply_merchant_ui_polish(STANDARD_SOURCE, "/admin/audit")
        self.assertIn("family=Cairo", rendered)
        self.assertIn("font-family:'Cairo'", rendered)
        self.assertIn(".ua-nav-link{font-weight:500!important}", rendered)
        self.assertIn(".ua-nav-link.active{font-weight:600!important}", rendered)
        self.assertIn(".ua-nav-section-title{", rendered)
        self.assertIn("font-weight:700!important", rendered)
        self.assertIn(".ua-content h1,.ua-content h2,.ua-content h3{font-weight:700!important}", rendered)
        self.assertIn(".ua-content th{font-weight:600!important}", rendered)
        self.assertIn(".ua-content td{font-weight:400!important}", rendered)
        self.assertIn(".ua-content .btn,.ua-content button{font-weight:500!important}", rendered)

    def test_cairo_and_weight_hierarchy_apply_to_ai_company_pages(self):
        source = """<html><head></head><body data-unified-admin-theme='ai'>
        <div class='ai-layout'><aside class='ai-sidebar'><nav class='ai-nav'><a class='active' href='/admin/company'>الرئيسية</a></nav></aside>
        <section class='ai-workspace'><h1>شركة بكجات الذكية</h1><h2>قسم</h2><p>وصف</p></section></div>
        </body></html>"""
        rendered = apply_merchant_ui_polish(source, "/admin/company")
        self.assertIn("family=Cairo", rendered)
        self.assertIn("body[data-unified-admin-theme='ai'] .ai-nav a{font-weight:500!important}", rendered)
        self.assertIn("body[data-unified-admin-theme='ai'] .ai-nav a.active{font-weight:600!important}", rendered)
        self.assertIn("body[data-unified-admin-theme='ai'] .ai-workspace h1,body[data-unified-admin-theme='ai'] .ai-workspace h2,body[data-unified-admin-theme='ai'] .ai-workspace h3{font-weight:700!important}", rendered)
        self.assertIn("body[data-unified-admin-theme='ai'] .ai-workspace p{font-weight:400!important}", rendered)

    def test_finance_translation_scope_is_preserved(self):
        source = "<html><head></head><body data-unified-admin-theme='standard'><main><span>Redeemed</span><span>active</span></main></body></html>"
        finance = apply_merchant_ui_polish(source, "/admin/merchants/1")
        audit = apply_merchant_ui_polish(source, "/admin/audit")
        self.assertIn(">مستخدمة<", finance)
        self.assertIn(">نشط<", finance)
        self.assertIn(">Redeemed<", audit)
        self.assertIn(">active<", audit)

    def test_non_admin_html_is_untouched(self):
        source = "<html><head></head><body><p>public</p></body></html>"
        self.assertEqual(apply_merchant_ui_polish(source, "/voucher/ABC"), source)


if __name__ == "__main__":
    unittest.main()
