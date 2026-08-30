import ast
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).parents[1] / "app" / "jood_whatsapp_context.py"


def load_policy():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    wanted = {
        "MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY",
        "MerchantCampaignChoiceAction",
        "merchant_campaign_choice_action",
    }
    body = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted:
                body.append(node)
        elif name in wanted:
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"dataclass": dataclass}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["merchant_campaign_choice_action"]


class MerchantHandoffPolicyTests(unittest.TestCase):
    def setUp(self):
        self.resolve = load_policy()
        self.context = SimpleNamespace(
            state_json={
                "direction": "outbound",
                "persona": "outbound_merchant_acquisition",
            }
        )

    def test_details_button_sends_approved_reply_then_hands_off(self):
        action = self.resolve("أرسلوا التفاصيل", "merchant", self.context)
        self.assertIsNotNone(action)
        self.assertIn("أبشروا بالسعد", action.reply)
        self.assertEqual(action.next_stage, "handed_off")

    def test_question_button_hands_off_without_automatic_reply(self):
        action = self.resolve("لدي استفسار", "merchant", self.context)
        self.assertIsNotNone(action)
        self.assertEqual(action.reply, "")

    def test_unexpected_text_hands_off_without_automatic_reply(self):
        action = self.resolve("ممكن توضحون أكثر؟", "merchant", self.context)
        self.assertIsNotNone(action)
        self.assertEqual(action.reply, "")

    def test_customer_context_is_not_affected(self):
        self.assertIsNone(self.resolve("مرحبا", "customer", self.context))


if __name__ == "__main__":
    unittest.main()
