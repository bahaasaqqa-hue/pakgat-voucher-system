from app.jood_whatsapp_context import (
    MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY,
    JoodWhatsAppContext,
    merchant_campaign_choice_action,
)


MERCHANT_REGISTER_URL = "https://merchant.pakgat.com/merchant/register"


def test_send_details_reply_contains_registration_link_only_for_choice_one():
    context = JoodWhatsAppContext(
        contact_id=1,
        mode="merchant",
        objective="merchant partnership",
        source="campaign",
        active=True,
        state_json={
            "direction": "outbound",
            "persona": "outbound_merchant_acquisition",
            "status": "active",
        },
    )

    choice_one = merchant_campaign_choice_action("أرسلوا التفاصيل", "merchant", context)
    choice_two = merchant_campaign_choice_action("لدي استفسار", "merchant", context)

    assert choice_one is not None
    assert choice_one.reply == MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY
    assert MERCHANT_REGISTER_URL in choice_one.reply
    assert "التحقق عبر نفاذ" in choice_one.reply

    assert choice_two is not None
    assert choice_two.reply == ""
    assert choice_two.handoff_details == "merchant_campaign_silent_human_takeover"
