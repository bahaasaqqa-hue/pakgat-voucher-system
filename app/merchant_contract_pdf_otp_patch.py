"""LibreOffice-safe three-page Pakgat agreement with OTP acceptance."""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from app import merchant_contract_pdf as contract_pdf


def _ltr(value: str) -> str:
    return f'<span class="ltr">{contract_pdf._e(value)}</span>'


def _row(label: str, value: str, *, ltr: bool = False) -> str:
    rendered = _ltr(value) if ltr else contract_pdf._e(value)
    return f'<tr><th>{contract_pdf._e(label)}</th><td>{rendered}</td></tr>'


def _paired_rows(items: list[tuple[str, str, bool]]) -> str:
    rows = []
    for index in range(0, len(items), 2):
        cells = []
        for label, value, ltr in items[index:index + 2]:
            rendered = _ltr(value) if ltr else contract_pdf._e(value)
            cells.append(f'<th>{contract_pdf._e(label)}</th><td>{rendered}</td>')
        if len(cells) == 1:
            cells.append('<th></th><td></td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    return ''.join(rows)


def _clause(number: int, title: str, body: str, *, page_title: str = "") -> str:
    classes = "clause"
    heading = f'<div class="terms-title">{contract_pdf._e(page_title)}</div>' if page_title else ""
    return (
        f'<div class="{classes}">'
        f'{heading}'
        f'<h3>{number}. {contract_pdf._e(title)}</h3>'
        f'<p>{contract_pdf._e(body)}</p>'
        '</div>'
    )


def build_contract_html_otp(data: contract_pdf.ContractData) -> str:
    merchant_rows = _paired_rows([
        ("اسم المنشأة", data.legal_name, False),
        ("السجل التجاري / الرقم الموحد", data.commercial_registration, True),
        ("النشاط", data.activity, False),
        ("الرقم الضريبي", data.tax_number, True),
        ("البنك", data.bank_name, False),
        ("IBAN", data.iban, True),
        ("العنوان", data.national_address, False),
        ("رقم الجوال", data.contact_phone, True),
        ("البريد الإلكتروني", data.contact_email, True),
        ("الموقع الإلكتروني", data.website or "لا يوجد", True),
        ("اسم الممثل", data.representative_name, False),
        ("صفة الممثل", data.representative_title, False),
    ])
    pakgat_rows = _paired_rows([
        ("السجل التجاري", "1009100740", True),
        ("الرقم الضريبي", "312531659100003", True),
        ("IBAN", "SA1710000026700000717001", True),
        ("الموقع الإلكتروني", "https://pakgat.com", True),
    ])

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
    @page { size:A4; margin:10mm 13mm 10mm; }
    html, body { margin:0; padding:0; }
    body { font-family:Arial,'Noto Sans Arabic',sans-serif; color:#172b4d; direction:rtl; background:#fff; font-size:9.5pt; text-align:right; }
    .page { page-break-after:auto; }
    .page-break { page-break-before:always; height:1px; margin:0; padding:0; font-size:1px; line-height:1px; color:#fff; }
    .brand { width:100%; table-layout:fixed; border-collapse:collapse; margin:0 0 6px; border-bottom:1.5px solid #164da8; }
    .brand td { padding:0 0 5px; vertical-align:middle; }
    .brand-logo-cell { width:55%; text-align:right; }
    .brand-logo { width:110px; height:52px; object-fit:contain; display:block; margin:0; }
    .page-label { width:45%; text-align:left; color:#536b91; font-size:8.5pt; font-weight:bold; }
    h1 { margin:4px 0 2px; text-align:center; color:#0b3f96; font-size:20pt; }
    .subtitle { text-align:center; color:#263b61; font-weight:bold; font-size:9.5pt; margin:0 0 7px; }
    .meta { width:100%; table-layout:fixed; border-collapse:collapse; margin-bottom:7px; }
    .meta td { width:50%; border:1px solid #d3dce9; background:#f7f9fc; padding:5px 8px; text-align:center; }
    .meta b { color:#0b3f96; }
    .section-title { width:100%; table-layout:fixed; border-collapse:collapse; margin:6px 0 4px; }
    .section-title td { background:#fff; color:#0b3f96; border-bottom:2px solid #0b3f96; padding:4px 2px; font-weight:bold; font-size:10.5pt; text-align:right; }
    .card { border:1px solid #d3dce9; padding:5px 7px; margin-bottom:5px; background:#fff; }
    .party-title { color:#0b3f96; font-size:9pt; font-weight:bold; margin:0 0 4px; padding-bottom:3px; border-bottom:1px solid #e4e9f1; text-align:right; }
    table.data { width:100%; table-layout:fixed; border-collapse:collapse; font-size:8.2pt; }
    table.data th, table.data td { border-bottom:1px solid #e4e9f1; padding:3px 5px; vertical-align:middle; text-align:right; }
    table.data th { width:19%; background:#f7f9fc; color:#254a80; font-weight:bold; }
    table.data td { width:31%; color:#172b4d; }
    .intro, .manual-note { padding:6px 8px; line-height:1.45; margin-bottom:5px; text-align:right; }
    .intro { border:1px solid #d8e0eb; }
    .manual-note { background:#f7f9fc; border:1px solid #d3dce9; border-right:3px solid #164da8; }
    .clause { border-bottom:1px solid #dce3ed; padding:4px 0 5px; page-break-inside:avoid; text-align:right; }
    .clause h3 { color:#0b3f96; margin:0 0 1px; font-size:10pt; }
    .clause p { margin:0; color:#263b61; font-size:8.3pt; line-height:1.36; text-align:right; }
    .terms-title { color:#0b3f96; border-bottom:2px solid #0b3f96; padding:3px 0 4px; margin-bottom:5px; font-weight:bold; font-size:10.5pt; text-align:right; }
    .approval-table { width:100%; table-layout:fixed; border-collapse:collapse; margin-top:5px; }
    .approval-table td { width:50%; border:1px solid #d3dce9; padding:6px 7px; vertical-align:top; text-align:right; }
    .approval-table h3 { margin:0 0 4px; color:#0b3f96; font-size:9.5pt; padding-bottom:3px; border-bottom:1px solid #e4e9f1; }
    .approval-line { margin:2px 0; font-size:8.3pt; line-height:1.35; }
    .activation { margin-top:5px; padding:5px 7px; background:#f7f9fc; border:1px solid #d3dce9; border-right:3px solid #164da8; color:#0b3f96; font-weight:bold; font-size:8.2pt; }
    .footer { width:100%; table-layout:fixed; border-collapse:collapse; margin-top:6px; border-top:1px solid #d3dce9; color:#617391; font-size:7.5pt; }
    .footer td { width:33.33%; padding-top:3px; }
    .footer .center { text-align:center; }
    .page-number { text-align:left; }
    .page-two-end { margin-bottom:28mm; }
    .ltr { direction:ltr; unicode-bidi:embed; display:inline-block; }
    """

    agreement = _ltr(data.agreement_number)
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{css}</style></head><body>
<section class="page">
  <table class="brand"><tr><td class="brand-logo-cell"><img class="brand-logo" src="pakgat-logo.jpg" alt="Pakgat"></td><td class="page-label">اتفاقية شراكة تجارية</td></tr></table>
  <h1>اتفاقية شراكة</h1>
  <div class="subtitle">لترويج وبيع العروض والقسائم الإلكترونية بين شركة تام العاصمة التجارية (Pakgat) والتاجر</div>
  <table class="meta"><tr><td><b>رقم الاتفاقية</b><br>{agreement}</td><td><b>التاريخ</b><br>{_ltr(data.agreement_date)}</td></tr></table>
  <table class="section-title"><tr><td>أولاً: أطراف الاتفاقية</td></tr></table>
  <div class="card"><div class="party-title">الطرف الأول: شركة تام العاصمة التجارية – المالكة لمنصة Pakgat.com</div><table class="data">
    {pakgat_rows}
  </table></div>
  <div class="card"><div class="party-title">الطرف الثاني: التاجر</div><table class="data">{merchant_rows}</table></div>
  <table class="section-title"><tr><td>ثانياً: التمهيد</td></tr></table>
  <div class="intro">حيث إن الطرف الأول يدير منصة إلكترونية متخصصة في تسويق وبيع العروض والباقات والقسائم الإلكترونية، ويرغب الطرف الثاني في عرض خدماته أو منتجاته عبر المنصة للوصول إلى عملاء جدد، فقد اتفق الطرفان – وهما بكامل أهليتهما المعتبرة – على ما يلي، ويعد هذا التمهيد جزءاً لا يتجزأ من الاتفاقية.</div>
  <div class="manual-note"><b>إجراء التوقيع والاعتماد:</b> يراجع التاجر هذه الاتفاقية داخل بوابة Pakgat ويؤكد موافقته عليها باستخدام رمز تحقق OTP مستقل يرسل إلى رقم الجوال المسجل. نجاح رمز التحقق يعد موافقة إلكترونية موثقة على رقم الاتفاقية المعروض، ثم ينتقل الطلب إلى مراجعة Pakgat النهائية. لا يتم تفعيل حساب التاجر تلقائياً.</div>
  <table class="footer"><tr><td>بكجات | Pakgat.com</td><td class="center">{agreement}</td><td class="page-number">صفحة 1 من 3</td></tr></table>
</section>
<section class="page">
  <p class="page-break">&nbsp;</p>
  {clauses_1}
  <table class="footer page-two-end"><tr><td>بكجات | Pakgat.com</td><td class="center">{agreement}</td><td class="page-number">صفحة 2 من 3</td></tr></table>
</section>
<section class="page">
  {clauses_2}
  <table class="section-title"><tr><td>رابعاً: الموافقة الإلكترونية والاعتماد النهائي</td></tr></table>
  <table class="approval-table"><tr>
    <td><h3>الطرف الأول – شركة تام العاصمة التجارية (Pakgat)</h3>
      <div class="approval-line">الاسم: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_NAME)}</div>
      <div class="approval-line">الصفة: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_TITLE)}</div>
      <div class="approval-line">الاعتماد: قرار Pakgat النهائي بعد مراجعة الطلب</div>
      <div class="approval-line">الحالة: لا يصبح الحساب Active إلا بعد الاعتماد النهائي</div>
    </td>
    <td><h3>الطرف الثاني – التاجر</h3>
      <div class="approval-line">الاسم: {contract_pdf._e(data.representative_name)}</div>
      <div class="approval-line">الصفة: {contract_pdf._e(data.representative_title)}</div>
      <div class="approval-line">الجوال: {_ltr(data.contact_phone)}</div>
      <div class="approval-line">الموافقة: إلكترونياً عبر OTP مخصص لهذه الاتفاقية</div>
      <div class="approval-line">رقم الاتفاقية: {agreement}</div>
    </td>
  </tr></table>
  <div class="activation">حالة التفعيل: نجاح OTP يثبت موافقة التاجر على الاتفاقية ولا يفعّل الحساب تلقائياً. يصبح الحساب Active فقط بعد الموافقة النهائية من Pakgat على طلب التسجيل.</div>
  <table class="footer"><tr><td>بكجات | Pakgat.com</td><td class="center">{agreement}</td><td class="page-number">صفحة 3 من 3</td></tr></table>
</section>
</body></html>'''


def render_contract_pdf_otp(data: contract_pdf.ContractData, *, converter=contract_pdf._libreoffice_converter) -> bytes:
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        source_path = root / "merchant-agreement.html"
        source_path.write_text(build_contract_html_otp(data), encoding="utf-8")

        # LibreOffice renders a normal local JPEG more reliably than a large data URI.
        uri = contract_pdf._logo_data_uri()
        try:
            logo_payload = base64.b64decode(uri.split(",", 1)[1])
        except Exception:
            raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None
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
