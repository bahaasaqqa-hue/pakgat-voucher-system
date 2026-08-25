"""Canonical Pakgat social accounts and privacy-safe UTM link generation."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


OFFICIAL_SOCIAL_ACCOUNTS = [
    {"platform": "instagram", "label": "Instagram", "handle": "@pakgat.sa", "url": "https://www.instagram.com/pakgat.sa"},
    {"platform": "tiktok", "label": "TikTok", "handle": "@pakgat.sa", "url": "https://www.tiktok.com/@pakgat.sa"},
    {"platform": "snapchat", "label": "Snapchat", "handle": "@pakgat.sa", "url": "https://www.snapchat.com/add/pakgat.sa"},
]


def build_utm_url(base_url: str, *, source: str, campaign: str, medium: str = "social", content: str = "") -> str:
    parts = urlsplit(str(base_url or "https://pakgat.com/"))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"utm_source": source, "utm_medium": medium, "utm_campaign": campaign})
    if content:
        query["utm_content"] = content
    return urlunsplit((parts.scheme or "https", parts.netloc or "pakgat.com", parts.path or "/", urlencode(query), parts.fragment))


def profile_utm_links(base_url: str = "https://pakgat.com/") -> dict[str, str]:
    return {row["platform"]: build_utm_url(base_url, source=row["platform"], campaign="profile") for row in OFFICIAL_SOCIAL_ACCOUNTS}
