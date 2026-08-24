import os
import unittest
import asyncio
from unittest.mock import patch
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import application as core
from app.customer_notifications import dispatch_due_customer_notifications


class CustomerNotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.CustomerNotification.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.voucher = core.create_voucher_record(
            self.db, "order:product:1", "product", "عرض", "شريك",
            "عميل", "0500000000", None,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_dispatcher_retries_failure_then_marks_sent(self):
        row = core.ensure_customer_notification(
            self.db, self.voucher, "voucher_issued", "message"
        )

        first = dispatch_due_customer_notifications(
            self.db, lambda phone, body: (_ for _ in ()).throw(TimeoutError("secret"))
        )
        self.assertEqual(first.failed, 1)
        self.db.refresh(row)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempt_count, 1)
        self.assertNotIn("secret", row.last_error)

        row.next_attempt_at = None
        self.db.commit()
        second = dispatch_due_customer_notifications(self.db, lambda phone, body: None)
        self.assertEqual(second.sent, 1)
        self.db.refresh(row)
        self.assertEqual(row.status, "sent")
        self.assertIsNotNone(row.sent_at)

    def test_approved_customer_issuance_message_matches_the_reviewed_copy(self):
        issued = core.build_voucher_whatsapp_message(
            "عميل", "عرض", "PKG-X", "100", "https://example.test/v/x",
            "مقدم", "9-5", "0500000000", "الرياض", "https://maps.test/x",
        )
        self.assertEqual(
            issued,
            "*قسيمتك جاهزة وأمورك طيبة!*\n\n"
            "أهلاً عميل 👋\n\n"
            "تم إصدار قسيمتك بنجاح، ومالك إلا اللي يرضيك:\n\n"
            "• *كود VIP:* خصم 5% على طلبك القادم\n"
            "• *العرض:* عرض\n"
            "• *القسيمة:* PKG-X\n"
            "• *رقم الطلب:* 100\n\n"
            "افتح قسيمتك واعرضها للتاجر أول ما تطلع له:\n"
            "https://example.test/v/x\n\n"
            "*تفاصيل مقدم الخدمة:*\n\n"
            "• *المكان:* مقدم\n"
            "• *أوقات العمل:* 9-5\n"
            "• *الجوال:* 0500000000\n"
            "• *العنوان:* الرياض\n"
            "• *الموقع:* https://maps.test/x\n\n"
            "🔒 _قسيمتك مسؤوليتك — لا توريها إلا للتاجر نفسه._\n\n"
            "https://pakgat.com\n"
            "*بدون قروشة.. بكجات تضبطك*\n\n"
            "علشان نتطمن إن كل شيء وصلك تمام، رد علينا برقم واحد بس:\n\n"
            "1 — وصلتني القسيمة\n"
            "2 — أحتاج فزعة من خدمة العملاء",
        )

    def test_approved_customer_redemption_message_contains_the_full_reviewed_tail(self):
        redeemed_at = core.now_utc()
        redeemed = core.build_redemption_whatsapp_message(
            "عميل", "عرض", "PKG-X", "100", "شريك", redeemed_at
        )
        self.assertEqual(
            redeemed,
            "✅ *تم استخدام قسيمتك وتتهنا بها!*\n\n"
            "يا هلا عميل 👋\n"
            "تم تأكيد استلامك للخدمة عند شريك بالتمام والكمال.\n\n"
            "• *العرض:* عرض\n"
            "• *رقم القسيمة:* PKG-X\n"
            "• *رقم الطلب:* 100\n"
            f"• *وقت الاستخدام:* {core.fmt_dt(redeemed_at)}\n\n"
            "⭐ *لأنك عميل Pakgat، قدرك عندنا عالي وصرت VIP.*\n\n"
            "🎁 يضبطك كود *VIP* بخصم 5% على طلبك الجاي!\n\n"
            "جاهز لتجربتك الجاية؟ اطّلع على العروض من هنا:\n\n"
            "https://pakgat.com\n"
            "*بدون قروشة.. بكجات تضبطك* ✨\n\n"
            "يهمنا رأيك علشان نطوّر خدمتك، كيف كانت تجربتك اليوم؟\n\n"
            "رد علينا برقم تقييمك من 1 إلى 5، بحيث 5 ممتازة وتبيّض الوجه.\n\n"
            "سعداء بخدمتك، ونشوفك على خير قريبًا 💙",
        )

    def test_approved_merchant_messages_keep_the_fixed_pin(self):
        sale = core.build_merchant_sale_whatsapp_message(
            "تاجر", "عرض", "100", 2, 2, "4321"
        )
        redeemed_at = core.now_utc()
        redeemed = core.build_merchant_redemption_whatsapp_message(
            "تاجر", "عرض", "PKG-X", "100", redeemed_at
        )
        self.assertEqual(
            sale,
            "🎉 *جاتك بيعة جديدة لعرض عرض!*\n\n"
            "يا هلا تاجر 👋\n"
            "تم شراء عرض بنجاح عبر Pakgat، وأموركم طيبة.\n\n"
            "• *رقم الطلب:* 100\n"
            "• *الكمية:* 2\n"
            "• *عدد القسائم:* 2\n\n"
            "القسيمة الحين جاهزة عند العميل، وبيمرّك ويوريك كود الـQR قبل ما يأخذ الخدمة.\n\n"
            "🔐 *الرمز السري لتأكيد الاستلام:* 4321\n\n"
            "_تأكّد من مسح الرمز أو إدخال الكود أول ما يحضر العميل وتسلّمه الخدمة._\n\n"
            "سعداء بشراكتنا معكم، ونطمح للأزين دايم 💙",
        )
        self.assertEqual(
            redeemed,
            "✅ *تم استخدام القسيمة وأموركم بالتمام!*\n\n"
            "يا هلا تاجر 👋\n"
            "تم تأكيد تسليم الخدمة بنجاح عبر Pakgat، وبيّض الله وجهك.\n\n"
            "• *العرض:* عرض\n"
            "• *رقم القسيمة:* PKG-X\n"
            "• *رقم الطلب:* 100\n"
            f"• *وقت الاستخدام:* {core.fmt_dt(redeemed_at)}\n\n"
            "🔒 _القسيمة تحولت الآن إلى «مستخدمة»، وما عاد تتفعّل مرة ثانية._\n\n"
            "سعداء جدًا بشراكتكم معنا، ونشوفك على خير 💙\n\n"
            "https://pakgat.com\n"
            "*بدون قروشة.. بكجات تضبطك* ✨",
        )

    def test_admin_voucher_creation_queues_the_real_customer_message(self):
        body = (
            b"order_id=ADMIN-TEST&product_id=P1&product_name=Test+Offer&"
            b"merchant_name=Pakgat&customer_name=Test&customer_phone=0504161514&"
            b"validity_days=7"
        )
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": "POST", "path": "/admin/vouchers/new", "headers": []}, receive=receive)
        with patch.object(core, "require_admin", return_value=True):
            response = asyncio.run(core.admin_create_voucher(request, self.db))

        self.assertEqual(response.status_code, 303)
        row = self.db.scalar(select(core.CustomerNotification))
        self.assertIsNotNone(row)
        self.assertEqual(row.notification_type, "voucher_issued")
        self.assertEqual(row.customer_phone, "966504161514")
        self.assertIn("1 — وصلتني القسيمة", row.message_body)


if __name__ == "__main__":
    unittest.main()
