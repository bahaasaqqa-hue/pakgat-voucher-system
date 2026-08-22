from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Any, Mapping, Optional

_TOKEN_CONTEXT = b"pakgat:whatsloop:webhook:v1"


@dataclass(frozen=True)
class InboundEvent:
    event_key: str
    event_type: str
    channel_id: Optional[int]
    message_id: Optional[str]
    sender: Optional[str]
    chat_id: Optional[str]
    text: Optional[str]
    from_me: Optional[bool]


def derive_webhook_token(admin_secret: str) -> str:
    return hmac.new(admin_secret.encode("utf-8"), _TOKEN_CONTEXT, hashlib.sha256).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def normalize_inbound_event(payload: Mapping[str, Any], raw_body: bytes) -> InboundEvent:
    data = _mapping(payload.get("data"))
    message = _mapping(data.get("message"))
    key = _mapping(data.get("key"))
    message_key = _mapping(message.get("key"))

    event_type = str(_first(payload.get("event"), payload.get("type"), data.get("event"), "unknown"))
    message_id_value = _first(
        data.get("id"),
        data.get("message_id"),
        data.get("messageId"),
        message.get("id"),
        message.get("message_id"),
        key.get("id"),
        message_key.get("id"),
    )
    message_id = str(message_id_value) if message_id_value is not None else None

    if message_id:
        event_key = f"{event_type}:{message_id}"
    else:
        event_key = "sha256:" + hashlib.sha256(raw_body).hexdigest()

    channel_id = _as_int(_first(payload.get("channel_id"), data.get("channel_id"), data.get("channelId")))
    sender_value = _first(
        data.get("from"),
        data.get("sender"),
        data.get("participant"),
        message.get("from"),
        key.get("participant"),
        message_key.get("participant"),
        key.get("remoteJid"),
        message_key.get("remoteJid"),
    )
    chat_value = _first(
        data.get("chat_id"),
        data.get("chatId"),
        data.get("to"),
        message.get("chat_id"),
        key.get("remoteJid"),
        message_key.get("remoteJid"),
    )
    text_value = _first(
        data.get("text"),
        data.get("body"),
        data.get("message" if isinstance(data.get("message"), str) else "__none__"),
        message.get("text"),
        message.get("body"),
        message.get("conversation"),
    )
    from_me = _as_bool(_first(data.get("from_me"), data.get("fromMe"), key.get("fromMe"), message_key.get("fromMe")))

    return InboundEvent(
        event_key=event_key,
        event_type=event_type,
        channel_id=channel_id,
        message_id=message_id,
        sender=str(sender_value) if sender_value is not None else None,
        chat_id=str(chat_value) if chat_value is not None else None,
        text=str(text_value) if text_value is not None else None,
        from_me=from_me,
    )
