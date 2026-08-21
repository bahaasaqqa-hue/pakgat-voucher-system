import unittest
from pathlib import Path


class EvidenceRendererCompatibilityTests(unittest.TestCase):
    def test_evidence_ui_does_not_replace_operational_opportunity_renderer(self):
        source = Path("app/ai_company_evidence_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("compact._opportunity_rows = _rows_with_links", source)
        self.assertNotIn("def _rows_with_links(", source)
        self.assertIn("_opportunities_with_evidence", source)
        self.assertIn("<div class='opp-id'>OP-", source)


if __name__ == "__main__":
    unittest.main()
