"""Uvicorn entry point for the Google-hosted Pakgat stack."""
from app.gce_entry import app
from app import salla_products_read_only as _salla_products_read_only  # noqa: F401 - Salla-approved Products Read also supplies product metadata
from app import ai_company as _ai_company  # noqa: F401 - registers AI Company routes/models
from app import salla_data as _salla_data  # noqa: F401 - captures signed Salla order snapshots
from app import ai_company_salla as _ai_company_salla  # noqa: F401 - adds Salla view to Control Center
from app import ai_company_growth as _ai_company_growth  # noqa: F401 - adds Sales/Growth/Product Intelligence
from app import google_analytics as _google_analytics  # noqa: F401 - GA4 read-only Data Hub snapshots
from app import google_search_console as _google_search_console  # noqa: F401 - Search Console read-only snapshots
from app import security_watch as _security_watch  # noqa: F401 - evidence-based security posture
from app import ai_company_sources as _ai_company_sources  # noqa: F401 - source inventory/status view
from app import ai_company_dispatch as _ai_company_dispatch  # noqa: F401 - manual opportunity assignment + WhatsLoop dispatch
from app import ai_company_agent_reporting as _ai_company_agent_reporting  # noqa: F401 - secure external agent reports + evidence
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
from app import jood_company_ops as _jood_company_ops  # noqa: F401 - Jood contacts, memory, routing, campaigns and call logs
from app import jood_whatsapp_context as _jood_whatsapp_context  # noqa: F401 - persistent outbound conversation objectives
from app import whatsloop_inbound as _whatsloop_inbound  # noqa: F401 - stateful Jood inbound WhatsLoop webhook + inbox
from app import jood_whatsapp_settings as _jood_whatsapp_settings  # noqa: F401 - persistent default outreach prompts
from app import jood_outbound as _jood_outbound  # noqa: F401 - Company AI outbound WhatsApp actions
from app import jood_whatsapp_campaign as _jood_whatsapp_campaign  # noqa: F401 - queued outbound WhatsApp campaigns
from app import jood_voice_bridge_ui as _jood_voice_bridge_ui  # noqa: F401 - half-duplex Phone Link/Voicemeeter voice bridge
from app import jood_voice_server_tts as _jood_voice_server_tts  # noqa: F401 - server-backed Zariyah playback for Chrome/Voicemeeter
from app import jood_voice_server_stt as _jood_voice_server_stt  # noqa: F401 - server-backed Vertex transcription for Voicemeeter capture
from app import jood_voice_live_bridge as _jood_voice_live_bridge  # noqa: F401 - Voicemeeter B1 MediaRecorder capture + automatic Jood call flow
from app import jood_voice_self_test_standalone as _jood_voice_self_test_standalone  # noqa: F401
from app import corporate_benefits as _corporate_benefits  # noqa: F401 - Corporate DB/admin base
from app import corporate_salla_profile_bridge as _corporate_salla_profile_bridge  # noqa: F401 - Salla owns login/email OTP; Google syncs eligibility/group
from app import corporate_salla_offers as _corporate_salla_offers  # noqa: F401 - optional customer-group discount offer provisioning
from app import ai_company_dashboard_v2 as _ai_company_dashboard_v2  # noqa: F401 - Pakgat AI visual/control experience
from app import ai_company_mission_control_ui as _ai_company_mission_control_ui  # noqa: F401 - Mission Control home, AI Core, command bar and intelligence panels
from app import jood_company_control_ui as _jood_company_control_ui  # noqa: F401 - unified Customer/Merchant WhatsApp/Voice control center
from app import jood_whatsapp_campaign_ui as _jood_whatsapp_campaign_ui  # noqa: F401 - Jood WhatsApp campaign control page
from app import jood_company_ui as _jood_company_ui  # noqa: F401 - Jood operations entry in Pakgat AI navigation
from app import corporate_salla_ui as _corporate_salla_ui  # noqa: F401 - final Corporate wording/readiness UI
from app import corporate_ai_bridge as _corporate_ai_bridge  # noqa: F401 - expose Corporate Benefits in AI Company
from app import merchant_finance as _merchant_finance  # noqa: F401 - merchant profiles, product commissions and weekly settlements
from app import merchant_contracts as _merchant_contracts  # noqa: F401 - merchant contract lifecycle and delivery audit
_merchant_contracts.ensure_merchant_contract_schema()
from app import merchant_contract_admin_actions as _merchant_contract_admin_actions  # noqa: F401 - merchant review actions
_merchant_contracts.merchant_contract_summary_html = _merchant_contract_admin_actions.merchant_contract_summary_html
from app import merchant_portal as _merchant_portal  # noqa: F401 - public merchant WhatsApp OTP portal
_merchant_portal.ensure_merchant_portal_schema()
from app import merchant_onboarding as _merchant_onboarding  # noqa: F401 - self-service merchant registration, documents and review lifecycle
_merchant_onboarding.ensure_merchant_onboarding_schema()
from app import merchant_onboarding_ui as _merchant_onboarding_ui  # noqa: F401 - friendly partner registration presentation
from app import merchant_onboarding_brand_assets as _merchant_onboarding_brand_assets  # noqa: F401 - official Pakgat onboarding brand assets
from app import merchant_finance_hooks as _merchant_finance_hooks  # noqa: F401 - refund/cancel, payable and API-security policy hooks
from app import merchant_profile_admin as _merchant_profile_admin  # noqa: F401 - merchant legal, VAT, contact and bank profile editing
from app import merchant_manual_contract as _merchant_manual_contract  # noqa: F401 - optional manual PDF fallback; Sadq/Nafath bypassed
from app import merchant_contract_otp as _merchant_contract_otp  # noqa: F401 - primary merchant agreement acceptance via dedicated OTP
_merchant_contract_otp.ensure_contract_otp_schema()
from app import merchant_contract_otp_compat as _merchant_contract_otp_compat  # noqa: F401 - safe audit access + stable agreement fingerprint
from app import merchant_contract_pdf_otp_patch as _merchant_contract_pdf_otp_patch  # noqa: F401 - OTP wording in branded contract
from app import merchant_voucher_page as _merchant_voucher_page  # noqa: F401 - merchant hours/contact/address on the existing voucher page
from app import voucher_lifecycle_dashboard as _voucher_lifecycle_dashboard  # noqa: F401 - automatic expiry sweep + refund/expired value dashboard
from app import admin_ai_typography as _admin_ai_typography  # noqa: F401 - scoped Pakgat AI typography normalization
from app import admin_unified_theme as _admin_unified_theme  # noqa: F401 - final global admin visual shell
from app import merchant_ui_cairo as _merchant_ui_cairo  # noqa: F401 - Cairo + Arabic finance presentation, load after unified theme

__all__ = ["app"]
