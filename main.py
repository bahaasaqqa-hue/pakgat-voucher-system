"""Uvicorn entry point for the Google-hosted Pakgat stack."""
from app.gce_entry import app
from app import ai_company as _ai_company  # noqa: F401 - registers AI Company routes/models
from app import salla_data as _salla_data  # noqa: F401 - captures signed Salla order snapshots
from app import ai_company_salla as _ai_company_salla  # noqa: F401 - adds Salla view to Control Center
from app import ai_company_growth as _ai_company_growth  # noqa: F401 - adds Sales/Growth/Product Intelligence
from app import ai_company_sources as _ai_company_sources  # noqa: F401 - source inventory/status view
from app import ai_company_dispatch as _ai_company_dispatch  # noqa: F401 - manual opportunity assignment + WhatsLoop dispatch

__all__ = ["app"]
