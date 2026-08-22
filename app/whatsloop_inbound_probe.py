"""Temporary safe probe for WhatsLoop webhook signature header discovery.

Logs only candidate header names, lengths and known scheme prefixes. It never
stores the webhook signing secret or complete signature value.
"""
from __future__ import annotations

from fastapi import Request

from app import application as core
from app.whatsloop_security import signature_header_metadata


@core.app.middleware("http")
async def whatsloop_signature_header_probe(request: Request, call_next):
    if request.url.path.startswith("/webhooks/whatsloop/"):
        metadata = signature_header_metadata(request.headers)
        db = None
        try:
            db = core.SessionLocal()
            core.log_event(
                db,
                "whatsloop_signature_header_probe",
                details="; ".join(metadata) if metadata else "no-signature-candidate-header",
            )
        except Exception:
            # Diagnostic logging must never block production webhook delivery.
            pass
        finally:
            if db is not None:
                db.close()
    return await call_next(request)
