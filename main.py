"""Uvicorn entry point for the Google-hosted Pakgat stack."""
from app.gce_entry import app
from app import ai_company as _ai_company  # noqa: F401 - registers AI Company routes/models
from app import salla_data as _salla_data  # noqa: F401 - captures signed Salla order snapshots
from app import ai_company_salla as _ai_company_salla  # noqa: F401 - adds Salla view to Control Center
from app import ai_company_growth as _ai_company_growth  # noqa: F401 - adds Sales/Growth/Product Intelligence
from app import ai_company_sources as _ai_company_sources  # noqa: F401 - source inventory/status view
from app import ai_company_dispatch as _ai_company_dispatch  # noqa: F401 - manual opportunity assignment + WhatsLoop dispatch
from app import ai_company_ar as _ai_company_ar  # noqa: F401 - Arabic UI + AI Company admin navigation
from app import ai_company_opportunity_compact as _ai_company_opportunity_compact  # noqa: F401 - focused radar + compact unified opportunity UX
from app import ai_company_compact_fix as _ai_company_compact_fix  # noqa: F401 - preserve all dashboard sections
from app import ai_company_evidence as _ai_company_evidence  # noqa: F401 - source links/images for opportunities
from app import ai_company_evidence_ui as _ai_company_evidence_ui  # noqa: F401 - show source evidence and enrich dispatch
from app import ai_company_competitor_watchlist as _ai_company_competitor_watchlist  # noqa: F401 - competitor/product radar sources

__all__ = ["app"]
