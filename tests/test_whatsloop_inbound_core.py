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


def test_normalize_inbound_event_extracts_real_whatsloop_data_object_shape():
    payload = {
        "id": "evt_trtuwjgoncr1yzyd77sv2mno",
        "object": "event",
        "type": "message.received",
        "api_version": "2026-06-01",
        "created": 1787429684,
        "tenant_id": "32a62723-295d-4196-ac53-50ab454854fc",
        "channel_id": None,
        "data": {
            "object": {
                "message_id": "ACFF842C6A9C36B7D0BEF068A41AFABD",
                "platform_message_id": 50796,
                "channel_id": 5,
                "conversation_id": 923,
                "contact_id": None,
                "group_id": "120363429327806767@g.us",
                "group_jid": "120363429327806767@g.us",
                "phone": "966504161514",
                "type": "text",
                "content": "مرحبا شاتي 3",
                "timestamp": "2026-08-22T20:14:43+00:00",
            }
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    event = normalize_inbound_event(payload, raw)
    assert event.event_type == "message.received"
    assert event.channel_id == 5
    assert event.message_id == "ACFF842C6A9C36B7D0BEF068A41AFABD"
    assert event.sender == "966504161514"
    assert event.chat_id == "120363429327806767@g.us"
    assert event.text == "مرحبا شاتي 3"
    assert event.event_key == "message.received:ACFF842C6A9C36B7D0BEF068A41AFABD"
