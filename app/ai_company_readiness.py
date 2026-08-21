"""Pure readiness helpers for Pakgat AI Company dashboards."""
from __future__ import annotations

import re


_SALLA_SCOPE_TERMS = {
    "Salla Products / Inventory": ("product",),
    "Salla Abandoned Carts": ("abandoned_cart", "abandonedcart", "cart"),
    "Salla Reviews": ("review",),
}


def _scope_tokens(scope: str) -> tuple[str, ...]:
    value = str(scope or "").strip().lower()
    if not value:
        return ()
    raw_tokens = re.split(r"[\s,;]+", value)
    return tuple(token.replace("-", "_") for token in raw_tokens if token)


def salla_source_access(source: str, oauth_connected: bool, scope: str) -> tuple[str, str]:
    """Return factual source access from OAuth presence plus the stored scope."""
    if not oauth_connected:
        return "Needs Integration", "OAuth not connected"

    terms = _SALLA_SCOPE_TERMS.get(source)
    if not terms:
        return "Needs Integration", "No scope rule defined"

    for token in _scope_tokens(scope):
        if "read" not in token:
            continue
        if any(term in token for term in terms):
            return "Readable", "OAuth connected; required read scope confirmed"

    return "Needs Integration", "OAuth connected; required read scope not present"


def summarize_system_statuses(statuses) -> dict[str, int]:
    """Separate operational completion from partial/pending blueprint status."""
    values = [str(status or "").strip() for status in statuses]
    complete = sum(value == "يعمل" for value in values)
    partial = sum("جزئي" in value for value in values)
    return {
        "total": len(values),
        "complete": complete,
        "partial": partial,
        "pending": len(values) - complete - partial,
    }
