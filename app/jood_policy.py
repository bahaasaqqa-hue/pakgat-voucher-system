from __future__ import annotations

import re
from typing import Optional

PAKGAT_HOME_URL = "https://pakgat.com/ar"
CAR_CARE_URL = (
    "https://pakgat.com/ar/"
    "%D8%A7%D9%84%D8%B9%D9%86%D8%A7%D9%8A%D8%A9-"
    "%D8%A8%D8%A7%D9%84%D8%B3%D9%8A%D8%A7%D8%B1%D8%A7%D8%AA/"
    "c1691767409"
)
LEGACY_CAR_CARE_PATH = "/ar/categories/car-care"
APPROVED_URLS = frozenset({PAKGAT_HOME_URL, CAR_CARE_URL})

_URL_RE = re.compile(r"https?://[^\s<>\"'\]\[)]+", re.IGNORECASE)
_LEGACY_ABSOLUTE_RE = re.compile(
    r"https?://(?:www\.)?pakgat\.com/ar/categories/car-care(?:[/?#][^\s<>\"']*)?",
    re.IGNORECASE,
)


def approved_url_for_intent(intent: str) -> Optional[str]:
    key = (intent or "").strip().lower()
    if key == "car_care":
        return CAR_CARE_URL
    if key in {"pakgat_home", "home"}:
        return PAKGAT_HOME_URL
    return None


def _replace_unapproved_url(match: re.Match[str], approved_urls: set[str]) -> str:
    url = match.group(0).rstrip(".,;:!?،؛")
    suffix = match.group(0)[len(url):]
    return (url if url in approved_urls else PAKGAT_HOME_URL) + suffix


def _is_car_care_request(customer_text: str) -> bool:
    value = " ".join(str(customer_text or "").strip().lower().split())
    return any(
        marker in value
        for marker in (
            "العناية بالسيارات",
            "عناية بالسيارات",
            "العنايه بالسيارات",
            "العنايه يالسيارات",
            "عروض السيارات",
            "car care",
        )
    )


def sanitize_jood_reply(
    text: str,
    *,
    allow_handoff_claim: bool = False,
    customer_text: str = "",
    approved_urls: set[str] | None = None,
) -> str:
    """Apply hard output guardrails before a Jood reply reaches any channel."""
    safe = str(text or "").strip()
    if not safe:
        return safe

    safe = _LEGACY_ABSOLUTE_RE.sub(CAR_CARE_URL, safe)
    safe = safe.replace(LEGACY_CAR_CARE_PATH, CAR_CARE_URL)
    allowed = set(APPROVED_URLS) | set(approved_urls or ())
    safe = _URL_RE.sub(lambda match: _replace_unapproved_url(match, allowed), safe)

    # Car-care replies must carry the canonical URL even if the model omitted it.
    # `customer_text` is preferred; falling back to the generated reply keeps the
    # safety behavior active for older call sites while they migrate.
    car_care_context = customer_text or safe
    if _is_car_care_request(car_care_context) and CAR_CARE_URL not in safe:
        safe = f"{safe}\n{CAR_CARE_URL}".strip()

    if not allow_handoff_claim:
        replacements = {
            "تم رفع بياناتكم": "أقدر أرفع بياناتكم",
            "تم رفع بياناتك": "أقدر أرفع بياناتك",
            "تم رفع طلبكم": "أقدر أرفع طلبكم",
            "تم رفع طلبك": "أقدر أرفع طلبك",
            "تم تسجيل بياناتكم": "أقدر أسجل بياناتكم",
            "تم تسجيل بياناتك": "أقدر أسجل بياناتك",
            "تم رفع حالتك": "أقدر أرفع حالتك",
            "تم رفع الحالة": "أقدر أرفع الحالة",
        }
        for completed, prospective in replacements.items():
            safe = safe.replace(completed, prospective)

    return safe
