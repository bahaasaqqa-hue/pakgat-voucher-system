"""Uvicorn entry point for the Google-hosted Pakgat stack."""
from app.gce_entry import app
from app import ai_company as _ai_company  # noqa: F401 - registers AI Company routes/models

__all__ = ["app"]
