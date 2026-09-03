"""LibreOffice-safe three-page Pakgat agreement with OTP acceptance."""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from app import merchant_contract_pdf as contract_pdf


def _ltr(value: str) -> str:
    return f'<span class="ltr">{contract_pdf._e(value)}</span>'


def _value(value: str, *, ltr: bool = False) -> str:
    return _ltr(value) if ltr else contract_pdf._e(value)


def _clause(number: int, title: str, body: str, *, page_title: str = "") -> str:
    heading = (
        f'<table class="terms-title" width="100%"><tr><td>{contract_pdf._e(page_title)}</td></tr></table>'
        if page_title else ""
    )
    return (
        '<table class="clause" width="100%"><tr><td>'
        f'{heading}'
        f'<p class="clause-title"><b>{number}. {contract_pdf._e(title)}</b></p>'
        f'<p class="clause-body">{contract_pdf._e(body)}</p>'
        '</td></tr></table>'
    )


def _brand_header() -> str:
    return '''<table class="brand" dir="ltr" width="100%"><tr>
      <td width="33%" align="left">&nbsp;</td>
      <td width="34%" class="brand-logo-cell" align="center"><img class="brand-logo" src="pakgat-logo.jpg" alt="Pakgat" width="88" height="42"></td>
      <td width="33%" class="brand-title" align="right"><span dir="rtl">اتفاقية شراكة تجارية</span></td>
    </tr></table>
    <table class="brand-rule" width="100%"><tr><td>&nbsp;</td></tr></table>'''


def _footer(agreement: str, page_number: int) -> str:
    return f'''<table class="footer" dir="ltr" width="100%"><tr>
      <td width="33%" align="left">بكجات | Pakgat.com</td>
      <td width="34%" align="center">{agreement}</td>
      <td width="33%" align="right"><span dir="rtl">صفحة {page_number} من 3</span></td>
    </tr></table>'''


def _prepare_logo_for_libreoffice(payload: bytes) -> bytes:
    """Give the JPEG a sane intrinsic DPI so LibreOffice cannot expand it to page size."""
    data = bytearray(payload)
    marker = data.find(b"JFIF\x00")
    if marker != -1 and marker + 12 <= len(data):
        units = marker + 7
        density = (1000).to_bytes(2, "big")
        data[units] = 1
        data[units + 1:units + 3] = density
        data[units + 3:units + 5] = density
    return bytes(data)


def _party_table(data: contract_pdf.ContractData) -> str:
    merchant = [
        ("اسم المنشأة", data.legal_name, False),
        ("النشاط", data.activity, False),
        ("السجل التجاري", data.commercial_registration, True),
        ("الرقم الضريبي", data.tax_number, True),
        ("البنك", data.bank_name, False),
        ("IBAN", data.iban, True),
        ("رقم الجوال", data.contact_phone, True),
        ("البريد الإلكتروني", data.contact_email, True),
        ("الموقع الإلكتروني", data.website or "لا يوجد", True),
        ("العنوان", data.national_address, False),
        ("اسم الممثل", data.representative_name, False),
        ("صفة الممثل", data.representative_title, False),
    ]
    pakgat = [
        ("الاسم", "شركة تام العاصمة التجارية (Pakgat)", False),
        ("السجل التجاري", "1009100740", True),
        ("الرقم الضريبي", "312531659100003", True),
        ("الموقع الإلكتروني", "https://pakgat.com", True),
        ("IBAN", "SA1710000026700000717001", True),
        ("العنوان", "المملكة العربية السعودية", False),
    ]

    rows = []
    for i in range(len(merchant)):
        ml, mv, mltr = merchant[i]
        if i < len(pakgat):
            pl, pv, pltr = pakgat[i]
            p_value = _value(pv, ltr=pltr)
            p_label = contract_pdf._e(pl)
        else:
            p_value = "&nbsp;"
            p_label = "&nbsp;"
        rows.append(
            '<tr>'
            f'<td class="party-value merchant-value" width="31%">{_value(mv, ltr=mltr)}</td>'
            f'<th class="party-label merchant-label" width="18%">{contract_pdf._e(ml)}</th>'
            '<td class="party-gap" width="2%">&nbsp;</td>'
            f'<td class="party-value pakgat-value" width="31%">{p_value}</td>'
            f'<th class="party-label pakgat-label" width="18%">{p_label}</th>'
            '</tr>'
        )

    return f'''<table class="parties-flat" dir="ltr" width="100%" cellspacing="0" cellpadding="0">
      <tr>
        <th colspan="2" class="party-head" bgcolor="#123d80">الطرف الثاني (التاجر)</th>
        <td class="party-gap" width="2%">&nbsp;</td>
        <th colspan="2" class="party-head" bgcolor="#123d80">الطرف الأول</th>
      </tr>
      {''.join(rows)}
    </table>'''


def _approval_table(data: contract_pdf.ContractData, agreement: str) -> str:
    merchant = [
        f'الاسم: {contract_pdf._e(data.representative_name)}',
        f'الصفة: {contract_pdf._e(data.representative_title)}',
        f'الجوال: {_ltr(data.contact_phone)}',
        'الموافقة: إلكترونياً عبر رمز تحقق OTP',
        f'رقم الاتفاقية: {agreement}',
    ]
    pakgat = [
        '<b>شركة تام العاصمة التجارية (Pakgat)</b>',
        f'الاسم: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_NAME)}',
        f'الصفة: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_TITLE)}',
        'الاعتماد: قرار Pakgat النهائي بعد مراجعة الطلب',
        'الحالة: لا يصبح الحساب Active إلا بعد الاعتماد النهائي',
    ]

    rows = []
    for left, right in zip(merchant, pakgat):
        rows.append(
            '<tr>'
            f'<td class="approval-cell" width="49%" dir="rtl">{left}</td>'
            '<td class="approval-gap" width="2%">&nbsp;</td>'
            f'<td class="approval-cell" width="49%" dir="rtl">{right}</td>'
            '</tr>'
        )

    return f'''<table class="approvals-flat" dir="ltr" width="100%" cellspacing="0" cellpadding="0">
      <tr>
        <th class="approval-head" width="49%" bgcolor="#123d80">الطرف الثاني (التاجر)</th>
        <td class="approval-gap" width="2%">&nbsp;</td>
        <th class="approval-head" width="49%" bgcolor="#123d80">الطرف الأول</th>
      </tr>
      {''.join(rows)}
    </table>'''


def build_contract_html_otp(data: contract_pdf.ContractData) -> str:
    clauses_1 = "".join([
        _clause(1, "التزامات الطرف الأول (Pakgat)", "تتولى Pakgat تصميم ونشر وتسويق العروض عبر المنصة، وإصدار القسائم الإلكترونية وتوفير نظام التحقق منها، وتحصيل قيمة الطلبات وتحويل صافي مستحقات التاجر وفق البيانات المالية المعتمدة، مع تقديم دعم المنصة. ولا تضمن Pakgat عدداً محدداً من المبيعات أو العملاء.", page_title="ثالثاً: الشروط والأحكام (1)"),
        _clause(2, "التزامات الطرف الثاني (التاجر)", "يلتزم التاجر بتقديم الخدمة أو المنتج بالمواصفات والسعر والشروط المعتمدة، وقبول القسائم الصالحة دون رسوم غير معلنة، وضمان صحة بياناته وأسعاره وتراخيصه والمحافظة على وسائل التحقق، ويتحمل المسؤولية النظامية عن جودة ما يقدمه وأي مطالبات ناشئة عنه."),
        _clause(3, "القسائم الإلكترونية", "تصدر لكل عملية شراء قسيمة برمز تحقق فريد تستخدم لمرة واحدة، وتعد مستخدمة بعد اعتمادها عبر النظام، ولا يجوز إعادة استخدامها أو قبولها بعد انتهاء صلاحيتها إلا باستثناء مكتوب من Pakgat لحماية حقوق العميل."),
        _clause(4, "التسوية المالية", "تحول Pakgat صافي مستحقات التاجر إلى الآيبان المسجل وفق دورة التسوية المعتمدة بعد خصم المبالغ المستردة والإلغاءات والأخطاء المحاسبية والرسوم المتفق عليها. ويعد كشف التسوية أساساً للمراجعة، ويكون الاعتراض خلال 7 أيام عمل من إرساله."),
        _clause(5, "الإلغاء والاسترجاع وحقوق العملاء", "تخضع طلبات الإلغاء والاستبدال والاسترجاع لسياسات Pakgat المعلنة وبما يتفق مع الأنظمة. وإذا ألغي الطلب أو تعذر على التاجر تقديم الخدمة أو المنتج لسبب يعود إليه، يلتزم بمعالجة حقوق العملاء وإعادة المبالغ المستحقة أو تنفيذ البديل الذي تعتمده Pakgat."),
        _clause(6, "التسويق والملكية الفكرية", "تبقى حقوق الملكية الفكرية والعلامات التجارية لكل طرف ملكاً له. ويمنح التاجر Pakgat ترخيصاً غير حصري ومجانياً طوال مدة التعاون لاستخدام اسمه وشعاره وصوره ومواد العروض لأغراض إعداد الصفحات والتسويق والإعلان في قنوات Pakgat وشركائها دون نقل ملكية تلك الحقوق."),
        _clause(7, "السرية وحماية البيانات", "يلتزم الطرفان بسرية المعلومات التجارية والمالية وبيانات العملاء وعدم استخدامها إلا بالقدر اللازم لتنفيذ الاتفاقية أو وفق ما تتطلبه الأنظمة، واتخاذ التدابير المناسبة لحماية البيانات الواقعة تحت سيطرة كل طرف وعدم مشاركتها مع غير المخولين."),
    ])

    clauses_2 = "".join([
        _clause(8, "حدود الصلاحيات والتعديلات", "لا يعتد بأي تعديل على الشروط التجارية أو الخصومات أو الالتزامات أو الوعود بالمبيعات أو الميزانيات الإعلانية أو الحصرية أو آجال السداد إلا بموافقة كتابية صادرة من Pakgat. ولا يجوز لأي شخص غير مفوض قبض مبالغ باسم Pakgat أو إبرام التزام مالي أو قانوني باسمها.", page_title="ثالثاً: الشروط والأحكام (2)"),
        _clause(9, "عدم الحصرية", "ما لم يتفق الطرفان كتابة على خلاف ذلك، تعد هذه الاتفاقية غير حصرية، ويجوز لكل طرف التعامل مع أطراف أخرى شريطة عدم استخدام المعلومات السرية للطرف الآخر أو الإخلال بالطلبات والعروض القائمة وحقوق العملاء."),
        _clause(10, "مدة الاتفاقية وإنهاؤها", "تسري الاتفاقية من تاريخ توقيعها وتستمر حتى انتهاء العروض النشطة وتسوية الالتزامات المالية المتعلقة بها. ويجوز لأي من الطرفين إنهاؤها عند الإخلال الجوهري أو مخالفة الأنظمة أو توقف النشاط أو إساءة استخدام المنصة، مع بقاء حقوق العملاء والمستحقات والالتزامات السابقة نافذة حتى تسويتها."),
        _clause(11, "القوة القاهرة", "لا يتحمل أي من الطرفين مسؤولية التأخير أو عدم التنفيذ الناتج مباشرة عن ظروف خارجة عن الإرادة لا يمكن توقعها أو دفعها بصورة معقولة، مع التزام الطرف المتأثر بإشعار الطرف الآخر واتخاذ ما يمكن لتقليل الأثر."),
        _clause(12, "القانون والاختصاص", "تخضع هذه الاتفاقية لأنظمة المملكة العربية السعودية. ويسعى الطرفان أولاً إلى تسوية أي خلاف ودياً خلال 15 يوم عمل من تاريخ الإشعار الكتابي، فإن تعذر ذلك فيكون الاختصاص للمحاكم المختصة داخل المملكة العربية السعودية."),
        _clause(13, "أحكام عامة", "تمثل هذه الاتفاقية كامل التفاهم بين الطرفين، ولا تعدل إلا كتابة وبموافقتهما. وإذا أصبح أي بند غير نافذ يبقى باقي الاتفاق نافذاً بالقدر الذي يسمح به النظام، ولكل طرف نسخة للعمل بموجبها."),
    ])

    css = """
    @page { size:A4; margin:8mm 10mm 8mm; }
    html, body { margin:0; padding:0; }
    body { font-family:Arial,'Noto Sans Arabic',sans-serif; color:#172b4d; direction:rtl; background:#fff; font-size:8pt; text-align:right; }
    table { border-collapse:collapse; }
    .page { width:100%; }
    .page-break { page-break-before:always; height:1px; line-height:1px; font-size:1px; margin:0; padding:0; }

    .brand { table-layout:fixed; margin:0 0 2px; }
    .brand td { border:0; padding:0 0 3px; vertical-align:middle; }
    .brand-title { color:#123d80; font-size:15pt; font-weight:bold; white-space:nowrap; }
    .brand-logo-cell { text-align:center; }
    .brand-logo { width:88px; height:42px; }
    .brand-rule td { border-bottom:2px solid #123d80; height:1px; padding:0; }

    .subtitle { margin:6px 0 7px; text-align:center; font-size:8.4pt; line-height:1.3; }
    .meta { width:64%; margin:0 auto 6px; table-layout:fixed; }
    .meta td { border:1px solid #cdd9ea; background:#f7f9fc; padding:4px 7px; text-align:center; }
    .meta b { color:#123d80; }

    .section-title { margin:6px 0 5px; table-layout:fixed; }
    .section-title td { color:#123d80; border-bottom:1px solid #c6d3e6; padding:4px 0; font-weight:bold; font-size:10.4pt; text-align:center; }

    .parties-flat { width:100%; table-layout:fixed; margin:0 0 6px; }
    .party-head { background:#123d80; color:#fff; font-size:10pt; font-weight:bold; padding:5px 6px; text-align:center; }
    .party-label, .party-value { border:1px solid #e1e7ef; padding:3px 5px; vertical-align:middle; }
    .party-label { background:#f7f9fc; color:#254a80; font-weight:bold; text-align:right; direction:rtl; }
    .party-value { background:#fff; color:#172b4d; text-align:right; direction:rtl; }
    .party-gap { border:0 !important; background:#fff !important; }

    .intro-table { width:100%; table-layout:fixed; margin-bottom:5px; }
    .intro-table td { padding:4px 7px 6px; line-height:1.45; text-align:right; }
    .signing-box { width:100%; table-layout:fixed; border:1px solid #cdd9ea; margin-bottom:5px; }
    .signing-box td { padding:6px 9px; text-align:center; line-height:1.4; }
    .signing-title { color:#123d80; font-weight:bold; font-size:9pt; }
    .signing-separator { border-top:1px solid #d9e2ee; height:1px; padding:0 !important; }

    .terms-title { width:100%; table-layout:fixed; margin:0 0 5px; }
    .terms-title td { color:#123d80; border-bottom:2px solid #123d80; padding:3px 0 5px; font-weight:bold; font-size:10.5pt; text-align:center; }
    .clause { table-layout:fixed; page-break-inside:avoid; margin:0 0 3px; }
    .clause > tbody > tr > td { padding:3px 0 4px; border-bottom:1px solid #e2e8f0; }
    .clause-title { color:#123d80; font-size:10pt; margin:0 0 2px; text-align:right; }
    .clause-body { color:#263b61; font-size:7.9pt; line-height:1.38; margin:0; text-align:right; }

    .approvals-flat { width:100%; table-layout:fixed; margin-top:5px; }
    .approval-head { background:#123d80; color:#fff; font-size:9.5pt; font-weight:bold; padding:5px 6px; text-align:center; }
    .approval-cell { border-left:1px solid #cbd7e7; border-right:1px solid #cbd7e7; padding:3px 7px; text-align:right; font-size:7.7pt; line-height:1.32; background:#fff; }
    .approvals-flat tr:last-child .approval-cell { border-bottom:1px solid #cbd7e7; }
    .approval-gap { border:0 !important; background:#fff !important; }
    .activation-box { width:100%; table-layout:fixed; border:1px solid #cdd9ea; margin-top:6px; }
    .activation-box td { padding:7px 9px; background:#f7f9fc; color:#123d80; font-weight:bold; font-size:8.2pt; text-align:center; line-height:1.35; }

    .footer { width:100%; table-layout:fixed; margin-top:7px; border-top:2px solid #123d80; color:#526783; font-size:7.2pt; }
    .footer td { padding-top:4px; white-space:nowrap; }
    .ltr { direction:ltr; unicode-bidi:embed; display:inline-block; }
    """

    agreement = _ltr(data.agreement_number)
    header = _brand_header()
    parties = _party_table(data)
    approvals = _approval_table(data, agreement)

    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{css}</style></head><body>
<section class="page" id="contract-page-1">
  {header}
  <div class="subtitle">لترويج وبيع العروض والقسائم الإلكترونية بين شركة تام العاصمة التجارية (Pakgat) والتاجر.</div>
  <table class="meta" width="64%"><tr>
    <td width="50%"><b>التاريخ:</b> {_ltr(data.agreement_date)}</td>
    <td width="50%"><b>رقم الاتفاقية:</b> {agreement}</td>
  </tr></table>
  <table class="section-title" width="100%"><tr><td>أولاً: أطراف الاتفاقية</td></tr></table>
  {parties}
  <table class="section-title" width="100%"><tr><td>ثانياً: التمهيد</td></tr></table>
  <table class="intro-table"><tr><td>حيث إن الطرف الأول يدير منصة إلكترونية متخصصة في تسويق وبيع العروض والباقات والقسائم الإلكترونية، ويرغب الطرف الثاني في عرض خدماته أو منتجاته عبر المنصة للوصول إلى عملاء جدد، فقد اتفق الطرفان – وهما بكامل أهليتهما المعتبرة – على ما يلي، ويعد هذا التمهيد جزءاً لا يتجزأ من الاتفاقية.</td></tr></table>
  <table class="signing-box"><tr><td class="signing-title">إجراء التوقيع والاعتماد</td></tr><tr><td>يراجع التاجر هذه الاتفاقية داخل بوابة Pakgat ويؤكد موافقته عليها باستخدام رمز تحقق OTP مستقل يرسل إلى رقم الجوال المسجل.</td></tr><tr><td class="signing-separator">&nbsp;</td></tr><tr><td>نجاح رمز التحقق يعد موافقة إلكترونية موثقة على رقم الاتفاقية المعروض، ثم ينتقل الطلب إلى مراجعة Pakgat النهائية.<br><b>لا يتم تفعيل حساب التاجر تلقائياً.</b></td></tr></table>
  {_footer(agreement, 1)}
</section>

<div class="page-break">&nbsp;</div>
<section class="page" id="contract-page-2">
  {header}
  {clauses_1}
  {_footer(agreement, 2)}
</section>

<div class="page-break">&nbsp;</div>
<section class="page" id="contract-page-3">
  {header}
  {clauses_2}
  <table class="section-title" width="100%"><tr><td>رابعاً: الموافقة الإلكترونية والاعتماد النهائي</td></tr></table>
  {approvals}
  <table class="activation-box"><tr><td>نجاح OTP يثبت موافقة التاجر على الاتفاقية ولا يفعّل الحساب تلقائياً. يصبح الحساب Active فقط بعد الموافقة النهائية من Pakgat على طلب التسجيل.</td></tr></table>
  {_footer(agreement, 3)}
</section>
</body></html>'''


def render_contract_pdf_otp(data: contract_pdf.ContractData, *, converter=contract_pdf._libreoffice_converter) -> bytes:
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        source_path = root / "merchant-agreement.html"
        source_path.write_text(build_contract_html_otp(data), encoding="utf-8")

        uri = contract_pdf._logo_data_uri()
        try:
            logo_payload = base64.b64decode(uri.split(",", 1)[1])
        except Exception:
            raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None
        logo_payload = _prepare_logo_for_libreoffice(logo_payload)
        (root / "pakgat-logo.jpg").write_bytes(logo_payload)

        converter(source_path, root)
        pdf_path = root / "merchant-agreement.pdf"
        if not pdf_path.exists():
            raise contract_pdf.ContractRenderError("Merchant contract PDF was not generated")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF"):
            raise contract_pdf.ContractRenderError("Generated merchant contract PDF is invalid")
        return pdf


contract_pdf.build_contract_html = build_contract_html_otp
contract_pdf.render_contract_pdf = render_contract_pdf_otp

__all__ = ["build_contract_html_otp", "render_contract_pdf_otp"]
