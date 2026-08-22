"""Jood customer-service navigation integration for Pakgat AI Company."""
from app import ai_company_dashboard_v2 as v2

JOOD_NAV_ITEM = ("جود · واتساب", "/admin/company/whatsloop", "◍")


def _install_jood_nav_item() -> None:
    if any(href == JOOD_NAV_ITEM[1] for _, href, _ in v2.NAV_ITEMS):
        return
    index = next(
        (i + 1 for i, (_, href, _) in enumerate(v2.NAV_ITEMS) if href == "/admin/company/crm"),
        len(v2.NAV_ITEMS),
    )
    v2.NAV_ITEMS.insert(index, JOOD_NAV_ITEM)


_install_jood_nav_item()
