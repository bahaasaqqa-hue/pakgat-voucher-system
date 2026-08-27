import importlib.util
import unittest
from pathlib import Path


PATCHER_PATH = Path("deploy/gce/jood_merchant_followup_patch.py")


class JoodMerchantFollowupFallbackTests(unittest.TestCase):
    def _load_patcher(self):
        self.assertTrue(PATCHER_PATH.exists(), "merchant follow-up patcher is missing")
        spec = importlib.util.spec_from_file_location("jood_merchant_followup_patch", PATCHER_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_short_merchant_question_fallback_keeps_partnership_context(self):
        patcher = self._load_patcher()
        source = '''            if not validation or not validation.ok:\n                if direction == "outbound" and mode == "merchant":\n                    generated_reply = "أعتذر عن الرد السابق. معك جود من باكيجات بخصوص فرصة الشراكة؛ أرسل لي اسم النشاط والمدينة ونوع الخدمات لأوضح لكم الخطوة المناسبة."\n                elif direction == "outbound":\n'''

        patched = patcher.patch_source_text(source)

        self.assertNotIn("أرسل لي اسم النشاط والمدينة ونوع الخدمات", patched)
        self.assertIn("إذا تقصد كيف تتم آلية التعاون مع بكجات", patched)
        self.assertIn("وإذا كنت تقصد شيئًا آخر", patched)
        self.assertIn('direction == "outbound" and mode == "merchant"', patched)

    def test_patch_fails_closed_when_expected_fallback_is_not_present(self):
        patcher = self._load_patcher()
        with self.assertRaises(ValueError):
            patcher.patch_source_text("print('unrelated source')")


if __name__ == "__main__":
    unittest.main()
