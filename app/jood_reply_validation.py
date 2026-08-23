from __future__ import annotations

import re
from dataclasses import dataclass

from app.jood_policy import APPROVED_URLS

_MARKDOWN_URL = re.compile(r"\[(https?://[^\]]+)\]\((https?://[^)]+)\)", re.IGNORECASE)
_BROKEN_MARKDOWN_URL = re.compile(r"(https?://[^\s\]]+)\]\((https?://[^)]+)\)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_BAD_ENDINGS = (" بك", " مع", " من", " إلى", " في", " و", " أو", "...")


@dataclass(frozen=True)
class ReplyValidation:
    ok: bool
    reply: str
    reason: str = ""


def _raw_markdown_url(match: re.Match[str], allowed: set[str]) -> str:
    shown, target = match.group(1), match.group(2)
    return target if target in allowed else shown


def validate_and_clean_reply(
    reply: str,
    *,
    direction: str,
    last_commitment: str,
    commitment_fulfilled: bool,
    approved_urls: set[str] | None = None,
) -> ReplyValidation:
    allowed = set(APPROVED_URLS) | set(approved_urls or ())
    raw_url = lambda match: _raw_markdown_url(match, allowed)
    clean = _BROKEN_MARKDOWN_URL.sub(raw_url, str(reply or "").strip())
    clean = _MARKDOWN_URL.sub(raw_url, clean)
    seen: set[str] = set()

    def deduplicate(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = raw[-1] if raw[-1:] in ".,،؛!?" else ""
        url = raw[:-1] if suffix else raw
        if url not in allowed:
            return raw
        if url in seen:
            return ""
        seen.add(url)
        return url + suffix

    clean = _URL.sub(deduplicate, clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    urls = [value.rstrip(".,،؛!?") for value in _URL.findall(clean)]
    if any(url not in allowed for url in urls):
        return ReplyValidation(False, clean, "unapproved_url")
    ends_with_approved_url = any(clean.endswith(url) for url in allowed)
    if len(clean) < 20 or (clean.endswith(_BAD_ENDINGS) and not ends_with_approved_url):
        return ReplyValidation(False, clean, "incomplete_reply")
    strict_sales_template = clean.endswith("استخدم كود الخصم: VIP") and bool(urls)
    if not ends_with_approved_url and not strict_sales_template and clean[-1:] not in ".!?؟،؛😊🙂👍✅":
        return ReplyValidation(False, clean, "incomplete_sentence")
    if direction == "outbound" and any(
        phrase in clean for phrase in ("كيف أساعدك", "كيف أقدر أساعدك", "كيف اقدر اساعدك")
    ):
        return ReplyValidation(False, clean, "outbound_reset")
    if last_commitment.strip() and not commitment_fulfilled:
        return ReplyValidation(False, clean, "commitment_not_fulfilled")
    return ReplyValidation(True, clean)
