import unittest
from pathlib import Path

from app.admin_theme_core import ADMIN_NAV_ITEMS, active_nav_key, apply_admin_theme


LOGO = "data:image/svg+xml;base64,UEFLR0FU"


class UnifiedAdminThemeTests(unittest.TestCase):
    def test_standard_admin_page_gets_one_unified_shell(self):
        html = """<!doctype html><html lang='ar' dir='rtl'><head><title>لوحة إدارة القسائم | Pakgat</title></head><body><header class='topbar'><div>قديم</div></header><main class='wrap'><h1>لوحة إدارة القسائم</h1><section class='card'>المحتوى</section></main></body></html>"""
        rendered = apply_admin_theme(html, "/admin", LOGO)
        self.assertIn("data-unified-admin-theme='standard'", rendered)
        self.assertIn("class='ua-shell'", rendered)
        self.assertIn("class='ua-sidebar'", rendered)
        self.assertIn("class='ua-workspace'", rendered)
        self.assertNotIn("<header class='topbar'>", rendered)
        self.assertIn("لوحة إدارة القسائم", rendered)
        self.assertIn("المحتوى", rendered)

    def test_global_navigation_contains_all_principal_sections(self):
        rendered = apply_admin_theme("<html><head><title>X | Pakgat</title></head><body><main>X</main></body></html>", "/admin", LOGO)
        for _key, label, href, _icon in ADMIN_NAV_ITEMS:
            self.assertIn(label, rendered)
            self.assertIn(f"href='{href}'", rendered)
        self.assertIn("action='/admin/logout'", rendered)

    def test_active_navigation_tracks_path(self):
        self.assertEqual(active_nav_key("/admin"), "dashboard")
        self.assertEqual(active_nav_key("/admin/company/seo"), "company")
        self.assertEqual(active_nav_key("/admin/vouchers/new"), "new_voucher")
        self.assertEqual(active_nav_key("/admin/audit"), "audit")
        self.assertEqual(active_nav_key("/admin/integrations"), "integrations")
        self.assertEqual(active_nav_key("/admin/local-partners"), "partners")
        rendered = apply_admin_theme("<html><head><title>X</title></head><body>X</body></html>", "/admin/audit", LOGO)
        self.assertIn("data-nav-key='audit' class='ua-nav-link active'", rendered)

    def test_ai_company_page_is_not_double_wrapped(self):
        html = """<html><head><title>AI | Pakgat</title></head><body><div class='ai-layout'><aside class='ai-sidebar'>AI NAV</aside><section class='ai-workspace'><div class='ai-top'>TOP</div><main>Mission Control</main></section></div></body></html>"""
        rendered = apply_admin_theme(html, "/admin/company", LOGO)
        self.assertIn("data-unified-admin-theme='ai'", rendered)
        self.assertEqual(rendered.count("class='ai-layout'"), 1)
        self.assertNotIn("class='ua-shell'", rendered)
        self.assertIn("class='ua-ai-global'", rendered)
        self.assertIn("Mission Control", rendered)

    def test_login_is_branded_without_authenticated_sidebar(self):
        html = "<html><head><title>تسجيل الدخول | Pakgat</title></head><body><main><form><input name='username'></form></main></body></html>"
        rendered = apply_admin_theme(html, "/admin/login", LOGO)
        self.assertIn("data-unified-admin-theme='login'", rendered)
        self.assertIn("class='ua-login-brand'", rendered)
        self.assertIn(LOGO, rendered)
        self.assertNotIn("class='ua-sidebar'", rendered)
        self.assertNotIn("action='/admin/logout'", rendered)

    def test_non_admin_html_is_unchanged(self):
        html = "<html><body>public</body></html>"
        self.assertEqual(apply_admin_theme(html, "/voucher/ABC", LOGO), html)

    def test_transform_is_idempotent(self):
        html = "<html><head><title>X</title></head><body><main>X</main></body></html>"
        once = apply_admin_theme(html, "/admin", LOGO)
        twice = apply_admin_theme(once, "/admin", LOGO)
        self.assertEqual(once, twice)

    def test_design_system_styles_core_controls(self):
        rendered = apply_admin_theme("<html><head><title>X</title></head><body><main><table></table><input><select></select><textarea></textarea><button class='btn'>B</button><section class='card'>C</section></main></body></html>", "/admin", LOGO)
        for marker in (".ua-shell", ".ua-sidebar", ".ua-content", ".card", ".input", "textarea", "table", ".btn", ".badge", ".alert"):
            self.assertIn(marker, rendered)

    def test_middleware_source_guards_response_types_and_is_imported_last(self):
        middleware = Path("app/admin_unified_theme.py")
        self.assertTrue(middleware.exists())
        source = middleware.read_text(encoding="utf-8")
        self.assertIn('@core.app.middleware("http")', source)
        self.assertIn('path.startswith("/admin")', source)
        self.assertIn('300 <= response.status_code < 400', source)
        self.assertIn('"text/html" not in content_type', source)
        self.assertIn("apply_admin_theme", source)
        main_source = Path("main.py").read_text(encoding="utf-8")
        unified_pos = main_source.find("admin_unified_theme")
        corporate_pos = main_source.find("corporate_ai_bridge")
        self.assertGreater(unified_pos, corporate_pos)


if __name__ == "__main__":
    unittest.main()
