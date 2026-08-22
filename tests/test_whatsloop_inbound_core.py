import json

from app.whatsloop_inbound_core import derive_webhook_token, normalize_inbound_event


def test_derive_webhook_token_is_stable_and_not_raw_secret():
    token1 = derive_webhook_token("super-secret")
    token2 = derive_webhook_token("super-secret")
    assert token1 == token2
    assert token1 != "super-secret"
    assert len(token1) == 64


def test_normalize_inbound_event_extracts_common_message_fields():
    payload = {
        "event": "message.received",
        "channel_id": 5,
        "data": {
            "id": "msg-123",
            "from": "966500000001@s.whatsapp.net",
            "chat_id": "120363000000000000@g.us",
            "text": "مرحبا شاتي",
            "from_me": False,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    event = normalize_inbound_event(payload, raw)
    assert event.event_type == "message.received"
    assert event.channel_id == 5
    assert event.message_id == "msg-123"
    assert event.sender == "966500000001@s.whatsapp.net"
    assert event.chat_id == "120363000000000000@g.us"
    assert event.text == "مرحبا شاتي"
    assert event.from_me is False
    assert event.event_key == "message.received:msg-123"


def test_normalize_inbound_event_hashes_payload_when_message_id_missing():
    payload = {"event": "message.received", "data": {"text": "hello"}}
    raw = b'{"event":"message.received","data":{"text":"hello"}}'
    first = normalize_inbound_event(payload, raw)
    second = normalize_inbound_event(payload, raw)
    assert first.event_key == second.event_key
    assert first.event_key.startswith("sha256:")
