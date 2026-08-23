"""Jood omnichannel operations navigation integration for Pakgat AI Company."""
from app import ai_company_dashboard_v2 as v2

JOOD_NAV_ITEM = ("جود · العمليات", "/admin/company/jood/control", "◍")


def _install_jood_nav_item() -> None:
    # Remove old Jood entries, then install one omnichannel Company AI entry.
    v2.NAV_ITEMS[:] = [
        item for item in v2.NAV_ITEMS
        if item[1] not in {
            "/admin/company/whatsloop",
            "/admin/company/jood",
            "/admin/company/jood/control",
        }
    ]
    index = next(
        (i + 1 for i, (_, href, _) in enumerate(v2.NAV_ITEMS) if href == "/admin/company/crm"),
        len(v2.NAV_ITEMS),
    )
    v2.NAV_ITEMS.insert(index, JOOD_NAV_ITEM)


_install_jood_nav_item()
