"""Render/Uvicorn entry point."""
from app import application as voucher_application
from app.datahub import install_datahub_hooks

install_datahub_hooks(voucher_application)
app = voucher_application.app

__all__ = ["app"]
