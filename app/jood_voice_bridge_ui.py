from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import application as core
from app.jood_ai import JoodAIError, generate_jood_reply
from app.jood_company_ops import (
    CALL_OUTCOMES,
    CONTACT_TYPES,
    CompanyContact,
    JoodCallCampaign,
    JoodCallLog,
    JoodCallSession,
    append_turn,
    can_contact,
    conversation_key_for,
    create_handoff,
    load_recent_turns,
    next_callable_contact,
    route_jood_intent,
    trusted_context_for,
)
from app.jood_policy import sanitize_jood_reply

RIYADH_TZ = ZoneInfo("Asia/Riyadh")
JOOD_VOICE_NAME = "ar-SA-ZariyahNeural"


def append_transcript_line(transcript: str, speaker: str, text: str) -> str:
    clean = " ".join(str(text or "").strip().split())
    if not clean:
        return str(transcript or "")
    label = "JOOD" if str(speaker or "").strip().lower() in {"jood", "assistant", "model"} else "CUSTOMER"
    prefix = str(transcript or "").rstrip()
    line = f"{label}: {clean}"
    return f"{prefix}\n{line}".strip() if prefix else line


def outcome_flags(outcome: str) -> tuple[bool, bool]:
    value = str(outcome or "").strip().lower()
    human_follow_up = value in {"interested", "follow_up", "human_handoff"}
    do_not_contact = value == "do_not_contact"
    return human_follow_up, do_not_contact


def _parse_riyadh_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise ValueError("Invalid date/time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=RIYADH_TZ)
    return parsed.astimezone(timezone.utc)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _require_admin_api(request: Request) -> None:
    try:
        core.require_admin(request)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Admin authentication required") from exc


def _contact_context(contact: CompanyContact, campaign: JoodCallCampaign | None, text: str) -> str:
    context = trusted_context_for(text, contact.contact_type)
    known = []
    if contact.display_name:
        known.append(f"Contact display name: {contact.display_name}")
    if contact.business_name:
        known.append(f"Business name: {contact.business_name}")
    if contact.city:
        known.append(f"City: {contact.city}")
    if contact.notes:
        known.append(f"Approved Company AI notes: {contact.notes[:1200]}")
    if campaign:
        known.append(f"Outbound campaign goal: {campaign.goal[:1500]}")
    if known:
        context += "\n" + "\n".join(known)
    return context


@core.app.post("/admin/company/jood/campaigns")
async def create_call_campaign(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    value = lambda name, default="": str((form.get(name) or [default])[0]).strip()
    contact_type = value("contact_type", "customer").lower()
    if contact_type not in CONTACT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid contact type")
    try:
        start_at = _parse_riyadh_datetime(value("start_at"))
        end_at = _parse_riyadh_datetime(value("end_at"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    name = value("name") or f"Jood {contact_type.title()} Calls"
    goal = value("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="Campaign goal is required")
    row = JoodCallCampaign(
        name=name[:255],
        contact_type=contact_type,
        goal=goal[:5000],
        start_at=start_at,
        end_at=end_at,
        status="active",
        transcript_enabled=value("transcript_enabled", "1") != "0",
    )
    db.add(row)
    db.commit()
    return RedirectResponse("/admin/company/jood", status_code=303)


@core.app.get("/admin/company/jood/contacts/{contact_id}/call")
def start_contact_call(contact_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    contact = db.get(CompanyContact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not can_contact(contact):
        raise HTTPException(status_code=409, detail="Contact is marked do-not-contact")
    session = JoodCallSession(contact_id=contact.id, status="active", transcript="")
    db.add(session)
    db.commit()
    db.refresh(session)
    return RedirectResponse(f"/admin/company/jood/voice/{session.id}/bridge", status_code=303)


@core.app.get("/admin/company/jood/campaigns/{campaign_id}/next")
def start_campaign_next_call(campaign_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    campaign = db.get(JoodCallCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    contact = next_callable_contact(db, campaign, datetime.now(timezone.utc))
    if not contact:
        raise HTTPException(status_code=409, detail="No callable contact now: check call window, 30-second cooldown, or remaining contacts")
    session = JoodCallSession(contact_id=contact.id, campaign_id=campaign.id, status="active", transcript="")
    db.add(session)
    db.commit()
    db.refresh(session)
    return RedirectResponse(f"/admin/company/jood/voice/{session.id}/bridge", status_code=303)


@core.app.get("/admin/company/jood/voice/{session_id}/bridge", response_class=HTMLResponse)
def voice_bridge_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    session = db.get(JoodCallSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Voice session not found")
    contact = db.get(CompanyContact, session.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Lazy import avoids a module cycle: live_bridge uses append_transcript_line above.
    from app.jood_voice_live_bridge import build_live_voice_bridge_script

    script = build_live_voice_bridge_script(session.id)
    label = contact.display_name or contact.business_name or ("Customer" if contact.contact_type == "customer" else "Merchant")
    self_test_url = f"/admin/company/jood/voice/{session.id}/self-test"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='padding:24px;max-width:980px;margin:auto'>
        <div style='display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap'>
          <div><h1 style='margin-bottom:4px'>جود · Voice Session #{session.id}</h1>
          <p class='muted'>النوع: {core.esc(contact.contact_type)} · الجهة: {core.esc(label)}</p></div>
          <a class='btn btn-muted' href='/admin/company/jood'>رجوع إلى مركز جود</a>
        </div>

        <div class='alert' style='margin-top:16px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a'>
          <strong>رقم الاتصال عبر Phone Link:</strong> <span dir='ltr' style='font-size:20px'>{core.esc(contact.phone)}</span><br>
          اتصل يدويًا من Phone Link في Google Chrome. بعد أن يرد الطرف الآخر اضغط «تشغيل جود» مرة واحدة؛ بعدها جود تتكلم وتستمع وترد تلقائيًا.
        </div>

        <div id='voice-status' class='alert' style='margin-top:14px'>جود جاهزة للفحص.</div>
        <div class='card' style='padding:14px;margin-top:10px;background:#f8fafc'>
          <strong>فحص مسار المكالمة</strong>
          <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin-top:10px;font-size:14px'>
            <div id='diagnostic-browser'>⏳ Chrome</div>
            <div id='diagnostic-b1'>⏳ مدخل المكالمة</div>
            <div id='diagnostic-signal'>⏳ صوت الطرف الآخر</div>
            <div id='diagnostic-stt'>⏳ فهم الكلام</div>
            <div id='diagnostic-tts'>⏳ صوت جود</div>
          </div>
        </div>

        <div style='display:flex;gap:8px;flex-wrap:wrap;margin:14px 0'>
          <a class='btn btn-muted' href='{self_test_url}' target='_blank' rel='noopener'>اختبار صوت جود (صفحة مستقلة)</a>
          <button id='start-jood' class='btn btn-blue' type='button'>تشغيل جود</button>
          <button id='stop-listening' class='btn btn-muted' type='button'>إيقاف جود</button>
        </div>

        <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr;gap:12px'>
          <div class='card' style='padding:16px'><strong>آخر كلام للطرف الآخر</strong><div id='voice-transcript' style='margin-top:8px;min-height:70px'></div></div>
          <div class='card' style='padding:16px'><strong>آخر رد لجود</strong><div id='voice-reply' style='margin-top:8px;min-height:70px'></div></div>
        </div>

        <h3 style='margin-top:20px'>إنهاء المكالمة وحفظ Call Log</h3>
        <div style='display:flex;gap:7px;flex-wrap:wrap'>
          <button class='btn btn-blue' type='button' onclick="finishJoodCall('interested')">مهتم</button>
          <button class='btn btn-muted' type='button' onclick="finishJoodCall('follow_up')">متابعة</button>
          <button class='btn btn-muted' type='button' onclick="finishJoodCall('not_interested')">غير مهتم</button>
          <button class='btn btn-muted' type='button' onclick="finishJoodCall('no_answer')">لا يرد</button>
          <button class='btn btn-muted' type='button' onclick="finishJoodCall('busy')">مشغول</button>
          <button class='btn btn-muted' type='button' onclick="finishJoodCall('human_handoff')">تدخل بشري</button>
          <button class='btn btn-danger' type='button' onclick="finishJoodCall('do_not_contact')">لا تتواصلوا معي</button>
        </div>
        <p class='muted' style='margin-top:14px'>المسار الصوتي للمكالمة: Voicemeeter B1 → Pakgat STT → Jood Core → {JOOD_VOICE_NAME} → Chrome/Phone Link عبر مسار AUX/B2 الحالي.</p>
      </section>
    </main>
    <script>{script}</script>
    """
    return HTMLResponse(core.page_shell(f"جود Voice #{session.id}", body, admin=True))


@core.app.post("/admin/company/jood/voice/{session_id}/turn")
async def voice_turn(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    contact = db.get(CompanyContact, session.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON body required") from exc
    text = " ".join(str((payload or {}).get("text") or "").strip().split())[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="Transcript text is required")

    history = load_recent_turns(db, contact.id, limit=8)
    mode = contact.contact_type if contact.contact_type in CONTACT_TYPES else "customer"
    intent = route_jood_intent(text, mode)
    campaign = db.get(JoodCallCampaign, session.campaign_id) if session.campaign_id else None
    trusted_context = _contact_context(contact, campaign, text)
    conversation_key = conversation_key_for("voice", contact.id)
    append_turn(db, contact.id, "voice", "user", text, conversation_key)
    session.transcript = append_transcript_line(session.transcript or "", "customer", text)
    db.commit()

    allow_handoff_claim = False
    if intent == "human_handoff":
        create_handoff(
            db,
            contact.id,
            "customer_support" if mode == "customer" else "merchant_partnership",
            details=f"Voice session {session.id}: {text}",
        )
        allow_handoff_claim = True
        trusted_context += "\nA real handoff record has been created in Company AI."

    try:
        reply = await asyncio.to_thread(
            generate_jood_reply,
            text,
            history,
            mode,
            intent,
            trusted_context,
        )
    except JoodAIError as exc:
        core.log_event(db, "jood_voice_ai_failed", details=f"session={session.id}; error={str(exc)[:180]}")
        raise HTTPException(status_code=502, detail="Jood AI generation failed") from exc

    reply = sanitize_jood_reply(reply, allow_handoff_claim=allow_handoff_claim)
    append_turn(db, contact.id, "voice", "assistant", reply, conversation_key)
    session = db.get(JoodCallSession, session.id)
    session.transcript = append_transcript_line(session.transcript or "", "jood", reply)
    db.commit()
    return JSONResponse(
        {
            "success": True,
            "session_id": session.id,
            "mode": mode,
            "intent": intent,
            "reply": reply,
            "voice": JOOD_VOICE_NAME,
        }
    )


@core.app.post("/admin/company/jood/voice/{session_id}/finish")
async def finish_voice_call(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    contact = db.get(CompanyContact, session.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON body required") from exc
    outcome = str((payload or {}).get("outcome") or "").strip().lower()
    if outcome not in CALL_OUTCOMES:
        raise HTTPException(status_code=400, detail="Invalid call outcome")

    ended_at = datetime.now(timezone.utc)
    session.ended_at = ended_at
    session.status = "completed"
    transcript = session.transcript or ""
    human_follow_up, do_not_contact = outcome_flags(outcome)

    summary_prompt = (
        "مهمة داخلية فقط لفريق Pakgat وليست رسالة للعميل. "
        "لخص المكالمة التالية في جملة أو جملتين واضحتين، واذكر الاهتمام أو الاعتراض أو الخطوة التالية بدون اختراع معلومات:\n"
        + transcript[-3500:]
    )
    try:
        summary = await asyncio.to_thread(
            generate_jood_reply,
            summary_prompt,
            [],
            contact.contact_type,
            "internal_call_summary",
            "Return only an internal factual summary. Do not greet the customer and do not add URLs.",
        )
        summary = sanitize_jood_reply(summary)
    except Exception:
        summary = " ".join(transcript[-900:].split())[:900] or "لا يوجد نص كافٍ لتلخيص المكالمة."

    if do_not_contact:
        contact.status = "do_not_contact"
        if contact.contact_type == "merchant":
            contact.merchant_stage = "do_not_contact"
    elif contact.contact_type == "merchant" and outcome == "not_interested":
        contact.merchant_stage = "not_interested"
    elif contact.contact_type == "merchant" and outcome in {"interested", "human_handoff"}:
        create_handoff(
            db,
            contact.id,
            "merchant_partnership",
            details=f"Voice session {session.id}; outcome={outcome}; summary={summary[:1200]}",
        )

    duration = max(0, int((ended_at - session.started_at.astimezone(timezone.utc)).total_seconds()))
    log = JoodCallLog(
        session_id=session.id,
        contact_id=contact.id,
        campaign_id=session.campaign_id,
        contact_type=contact.contact_type,
        contact_name=contact.display_name or contact.business_name,
        phone=contact.phone,
        started_at=session.started_at,
        ended_at=ended_at,
        duration_seconds=duration,
        outcome=outcome,
        summary=summary[:4000],
        transcript=transcript if (not session.campaign_id or (db.get(JoodCallCampaign, session.campaign_id) or JoodCallCampaign(transcript_enabled=True)).transcript_enabled) else None,
        human_follow_up=human_follow_up,
        do_not_contact=do_not_contact,
    )
    db.add(log)
    campaign = db.get(JoodCallCampaign, session.campaign_id) if session.campaign_id else None
    if campaign:
        campaign.last_finished_at = ended_at
        campaign.updated_at = ended_at
    contact.last_contact_at = ended_at
    contact.updated_at = ended_at
    db.commit()
    core.log_event(db, "jood_voice_call_logged", details=f"session={session.id}; outcome={outcome}; contact_type={contact.contact_type}")
    return JSONResponse(
        {
            "success": True,
            "session_id": session.id,
            "outcome": outcome,
            "summary": summary,
            "human_follow_up": human_follow_up,
            "do_not_contact": do_not_contact,
        }
    )
