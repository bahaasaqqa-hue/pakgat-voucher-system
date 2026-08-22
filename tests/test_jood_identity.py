from app.jood_identity import (
    JOOD_NAME_AR,
    JOOD_NAME_EN,
    JOOD_ROLE_AR,
    JOOD_SIGNATURE_AR,
    JOOD_TEST_REPLY,
    JOOD_SYSTEM_PROMPT,
    should_jood_test_reply,
)


def test_jood_identity_is_external_pakgat_agent():
    assert JOOD_NAME_AR == "جود"
    assert JOOD_NAME_EN == "Jood"
    assert "العملاء" in JOOD_ROLE_AR
    assert "المبيعات" in JOOD_ROLE_AR
    assert JOOD_SIGNATURE_AR == "جود | بكجات"
    assert "جود" in JOOD_TEST_REPLY and "بكجات" in JOOD_TEST_REPLY
    assert "بهاء" in JOOD_SYSTEM_PROMPT
    assert "شاتي" in JOOD_SYSTEM_PROMPT


def test_jood_test_reply_only_triggers_for_direct_group_greeting():
    group = "120363429327806767@g.us"
    assert should_jood_test_reply("الو جود", group)
    assert should_jood_test_reply("ألو جود", group)
    assert should_jood_test_reply("مرحبا جود", group)
    assert should_jood_test_reply("هلا جود كيفك", group)
    assert not should_jood_test_reply("الو شاتي", group)
    assert not should_jood_test_reply("مرحبا", group)
    assert not should_jood_test_reply("الو جود", "966504161514@s.whatsapp.net")
