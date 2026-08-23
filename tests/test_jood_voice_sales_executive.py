import json
import unittest
from unittest.mock import patch

from app import jood_ai
from app import jood_voice_bridge_ui as base
from app import jood_voice_live_bridge as live
from app import jood_voice_server_tts as tts
from app.jood_company_ops import CompanyContact, JoodCallSession


class _FakeVoiceDB:
    def __init__(self, session, contact):
        self.session = session
        self.contact = contact

    def get(self, model, object_id):
        if model is JoodCallSession and object_id == self.session.id:
            return self.session
        if model is CompanyContact and object_id == self.contact.id:
            return self.contact
        return None


class _FakeCommunicator:
    seen = {}

    def __init__(self, text, voice, **kwargs):
        type(self).seen = {"text": text, "voice": voice, **kwargs}

    async def stream(self):
        yield {"type": "audio", "data": b"voice"}


class JoodVoiceSalesExecutiveTests(unittest.IsolatedAsyncioTestCase):
    def test_voice_bridge_has_one_canonical_owner_without_patch_installers(self):
        routes = [
            route
            for route in live.core.app.routes
            if getattr(route, "path", "") == "/admin/company/jood/voice/{session_id}/bridge"
            and "GET" in (getattr(route, "methods", set()) or set())
        ]

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].endpoint.__module__, "app.jood_voice_live_bridge")
        self.assertFalse(hasattr(live, "install_live_bridge_patch"))
        self.assertFalse(hasattr(tts, "install_server_tts_bridge_patch"))

    def test_bridge_renderer_loads_external_runtime_without_inline_voice_script(self):
        session = JoodCallSession(id=21, contact_id=7, status="active", transcript="")
        contact = CompanyContact(
            id=7,
            phone="966500000000",
            contact_type="merchant",
            business_name="Test Merchant",
            status="active",
        )
        db = _FakeVoiceDB(session, contact)

        with patch.object(base, "_admin_redirect", return_value=None):
            response = base.voice_bridge_page(21, object(), db)

        html = bytes(response.body).decode("utf-8")
        self.assertIn(
            "src='/admin/company/jood/voice/21/runtime.js'",
            html,
        )
        self.assertIn("id='start-jood'", html)
        self.assertNotIn("<script>const Recognition", html)
        self.assertNotIn("ابدأ استماع جود", html)

    async def test_zariyah_sales_voice_is_slower_softer_and_pronounces_brand(self):
        audio = await tts.synthesize_zariyah_mp3(
            "مرحباً، معك جود من بكجات.",
            communicator_factory=_FakeCommunicator,
        )

        self.assertEqual(audio, b"voice")
        self.assertEqual(_FakeCommunicator.seen["rate"], "-10%")
        self.assertEqual(_FakeCommunicator.seen["volume"], "-2%")
        self.assertEqual(_FakeCommunicator.seen["pitch"], "-4Hz")
        self.assertIn("بَكْجات", _FakeCommunicator.seen["text"])

    def test_merchant_prompt_defines_sales_role_and_truthful_whatsapp_followup(self):
        payload = jood_ai.build_vertex_payload(
            "عرفيني على الشراكة",
            mode="merchant",
            intent="merchant_acquisition",
        )
        system_text = payload["systemInstruction"]["parts"][0]["text"]

        self.assertIn("Merchant & Sales Executive", system_text)
        self.assertIn("لا تقولي إنك أرسلتِ واتساب", system_text)
        self.assertIn("موافقة الطرف الآخر", system_text)
        self.assertIn("العقد", system_text)
        self.assertIn("تحويل", system_text)


if __name__ == "__main__":
    unittest.main()
