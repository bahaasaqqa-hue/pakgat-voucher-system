"""Uvicorn entry point for the Google-hosted Pakgat stack."""
from app.gce_entry import app
from app import salla_products_read_only as _salla_products_read_only  # noqa: F401 - Salla-approved Products Read also supplies product metadata
from app import ai_company as _ai_company  # noqa: F401 - registers AI Company routes/models
from app import salla_data as _salla_data  # noqa: F401 - captures signed Salla order snapshots
from app import ai_company_salla as _ai_company_salla  # noqa: F401 - adds Salla view to Control Center
from app import ai_company_growth as _ai_company_growth  # noqa: F401 - adds Sales/Growth/Product Intelligence
from app import ai_company_sources as _ai_company_sources  # noqa: F401 - source inventory/status view
from app import ai_company_dispatch as _ai_company_dispatch  # noqa: F401 - manual opportunity assignment + WhatsLoop dispatch
from app import ai_company_ar as _ai_company_ar  # noqa: F401 - Arabic UI + AI Company admin navigation
from app import ai_company_opportunity_compact as _ai_company_opportunity_compact  # noqa: F401 - compact unified opportunity UX
from app import ai_company_compact_fix as _ai_company_compact_fix  # noqa: F401 - preserve all dashboard sections
from app import ai_company_evidence as _ai_company_evidence  # noqa: F401 - source links/images for opportunities
from app import ai_company_evidence_ui as _ai_company_evidence_ui  # noqa: F401 - show source evidence and enrich dispatch
from app import ai_company_competitor_watchlist as _ai_company_competitor_watchlist  # noqa: F401 - competitor/product radar sources
from app import ai_company_governance as _ai_company_governance  # noqa: F401 - approvals, decisions, CEO briefs
from app import ai_company_hunter as _ai_company_hunter  # noqa: F401 - merchant/supplier acquisition pipeline
from app import ai_company_store_ops as _ai_company_store_ops  # noqa: F401 - store operations quality watch
from app import ai_company_systems as _ai_company_systems  # noqa: F401 - 12-system hub + compact dashboard entry
from app import ai_company_run_company as _ai_company_run_company  # noqa: F401 - one-click AUTO-safe company cycle
from app import corporate_benefits as _corporate_benefits  # noqa: F401 - Corporate DB/admin base
from app import corporate_salla_profile_bridge as _corporate_salla_profile_bridge  # noqa: F401 - Salla owns login/email OTP; Google syncs eligibility/group
from app import corporate_salla_offers as _corporate_salla_offers  # noqa: F401 - optional customer-group discount offer provisioning
from app import ai_company_dashboard_v2 as _ai_company_dashboard_v2  # noqa: F401 - approved Pakgat AI visual/control experience
from app import corporate_salla_ui as _corporate_salla_ui  # noqa: F401 - final Corporate wording/readiness UI
from app import corporate_ai_bridge as _corporate_ai_bridge  # noqa: F401 - expose Corporate Benefits in AI Company, import LAST


_original_ai_company_layout_wrap = _ai_company_dashboard_v2._layout_wrap


def _admin_company_layout_wrap(html: str, path: str) -> str:
    html = _original_ai_company_layout_wrap(html, path)
    if path.rstrip("/") != "/admin/company":
        return html

    html = html.replace("100.0/100", "100/100")
    marker = "<div class='ai-top-actions'>"
    back_link = "<a class='ai-pill' href='/admin'>← رجوع إلى لوحة الإدارة</a>"
    return html.replace(marker, marker + back_link, 1)


_ai_company_dashboard_v2._layout_wrap = _admin_company_layout_wrap

__all__ = ["app"]
