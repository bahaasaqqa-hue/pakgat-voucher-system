"""Jood omnichannel operations navigation integration for Pakgat AI Company."""
from app import ai_company_dashboard_v2 as v2

JOOD_NAV_ITEMS = [
    ("جود · العمليات", "/admin/company/jood/control", "◍"),
    ("جود · حملات واتساب", "/admin/company/jood/whatsapp-campaigns", "✦"),
]


def _install_jood_nav_items() -> None:
    managed_hrefs = {
        "/admin/company/whatsloop",
        "/admin/company/jood",
        "/admin/company/jood/control",
        "/admin/company/jood/whatsapp-campaigns",
    }
    v2.NAV_ITEMS[:] = [item for item in v2.NAV_ITEMS if item[1] not in managed_hrefs]
    index = next(
        (i + 1 for i, (_, href, _) in enumerate(v2.NAV_ITEMS) if href == "/admin/company/crm"),
        len(v2.NAV_ITEMS),
    )
    for offset, item in enumerate(JOOD_NAV_ITEMS):
        v2.NAV_ITEMS.insert(index + offset, item)


_install_jood_nav_items()
