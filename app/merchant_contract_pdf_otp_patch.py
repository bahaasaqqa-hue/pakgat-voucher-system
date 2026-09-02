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


def _clause(number: int, title: str, body: str) -> str:
    return (
        '<div class="clause">'
        f'<h3>{number}. {contract_pdf._e(title)}</h3>'
        f'<p>{contract_pdf._e(body)}</p>'
        '</div>'
    )


def build_contract_html_otp(data: contract_pdf.ContractData) -> str:
    merchant_rows = "".join([
        _row("اسم المنشأة", data.legal_name),
        _row("السجل التجاري / الرقم الموحد", data.commercial_registration, ltr=True),
        _row("النشاط", data.activity),
        _row("الرقم الضريبي", data.tax_number, ltr=True),
        _row("البنك", data.bank_name),
        _row("IBAN", data.iban, ltr=True),
        _row("العنوان", data.national_address),
        _row("رقم الجوال", data.contact_phone, ltr=True),
        _row("البريد الإلكتروني", data.contact_email, ltr=True),
        _row("الموقع الإلكتروني", data.website or "لا يوجد", ltr=True),
        _row("اسم الممثل", data.representative_name),
        _row("صفة الممثل", data.representative_title),
    ])

    clauses_1 = "".join([
        _clause(1, "التزامات الطرف الأول (Pakgat)", "تتولى Pakgat تصميم ونشر وتسويق العروض عبر المنصة، وإصدار القسائم الإلكترونية وتوفير نظام التحقق منها، وتحصيل قيمة الطلبات وتحويل صافي مستحقات التاجر وفق البيانات المالية المعتمدة، مع تقديم دعم المنصة. ولا تضمن Pakgat عدداً محدداً من المبيعات أو العملاء."),
        _clause(2, "التزامات الطرف الثاني (التاجر)", "يلتزم التاجر بتقديم الخدمة أو المنتج بالمواصفات والسعر والشروط المعتمدة، وقبول القسائم الصالحة دون رسوم غير معلنة، وضمان صحة بياناته وأسعاره وتراخيصه والمحافظة على وسائل التحقق، ويتحمل المسؤولية النظامية عن جودة ما يقدمه وأي مطالبات ناشئة عنه."),
        _clause(3, "القسائم الإلكترونية", "تصدر لكل عملية شراء قسيمة برمز تحقق فريد تستخدم لمرة واحدة، وتعد مستخدمة بعد اعتمادها عبر النظام، ولا يجوز إعادة استخدامها أو قبولها بعد انتهاء صلاحيتها إلا باستثناء مكتوب من Pakgat لحماية حقوق العميل."),
        _clause(4, "التسوية المالية", "تحول Pakgat صافي مستحقات التاجر إلى الآيبان المسجل وفق دورة التسوية المعتمدة بعد خصم المبالغ المستردة والإلغاءات والأخطاء المحاسبية والرسوم المتفق عليها. ويعد كشف التسوية أساساً للمراجعة، ويكون الاعتراض خلال 7 أيام عمل من إرساله."),
        _clause(5, "الإلغاء والاسترجاع وحقوق العملاء", "تخضع طلبات الإلغاء والاستبدال والاسترجاع لسياسات Pakgat المعلنة وبما يتفق مع الأنظمة. وإذا ألغي الطلب أو تعذر على التاجر تقديم الخدمة أو المنتج لسبب يعود إليه، يلتزم بمعالجة حقوق العملاء وإعادة المبالغ المستحقة أو تنفيذ البديل الذي تعتمده Pakgat."),
        _clause(6, "التسويق والملكية الفكرية", "تبقى حقوق الملكية الفكرية والعلامات التجارية لكل طرف ملكاً له. ويمنح التاجر Pakgat ترخيصاً غير حصري ومجانياً طوال مدة التعاون لاستخدام اسمه وشعاره وصوره ومواد العروض لأغراض إعداد الصفحات والتسويق والإعلان في قنوات Pakgat وشركائها دون نقل ملكية تلك الحقوق."),
        _clause(7, "السرية وحماية البيانات", "يلتزم الطرفان بسرية المعلومات التجارية والمالية وبيانات العملاء وعدم استخدامها إلا بالقدر اللازم لتنفيذ الاتفاقية أو وفق ما تتطلبه الأنظمة، واتخاذ التدابير المناسبة لحماية البيانات الواقعة تحت سيطرة كل طرف وعدم مشاركتها مع غير المخولين."),
    ])

    clauses_2 = "".join([
        _clause(8, "حدود الصلاحيات والتعديلات", "لا يعتد بأي تعديل على الشروط التجارية أو الخصومات أو الالتزامات أو الوعود بالمبيعات أو الميزانيات الإعلانية أو الحصرية أو آجال السداد إلا بموافقة كتابية صادرة من Pakgat. ولا يجوز لأي شخص غير مفوض قبض مبالغ باسم Pakgat أو إبرام التزام مالي أو قانوني باسمها."),
        _clause(9, "عدم الحصرية", "ما لم يتفق الطرفان كتابة على خلاف ذلك، تعد هذه الاتفاقية غير حصرية، ويجوز لكل طرف التعامل مع أطراف أخرى شريطة عدم استخدام المعلومات السرية للطرف الآخر أو الإخلال بالطلبات والعروض القائمة وحقوق العملاء."),
        _clause(10, "مدة الاتفاقية وإنهاؤها", "تسري الاتفاقية من تاريخ توقيعها وتستمر حتى انتهاء العروض النشطة وتسوية الالتزامات المالية المتعلقة بها. ويجوز لأي من الطرفين إنهاؤها عند الإخلال الجوهري أو مخالفة الأنظمة أو توقف النشاط أو إساءة استخدام المنصة، مع بقاء حقوق العملاء والمستحقات والالتزامات السابقة نافذة حتى تسويتها."),
        _clause(11, "القوة القاهرة", "لا يتحمل أي من الطرفين مسؤولية التأخير أو عدم التنفيذ الناتج مباشرة عن ظروف خارجة عن الإرادة لا يمكن توقعها أو دفعها بصورة معقولة، مع التزام الطرف المتأثر بإشعار الطرف الآخر واتخاذ ما يمكن لتقليل الأثر."),
        _clause(12, "القانون والاختصاص", "تخضع هذه الاتفاقية لأنظمة المملكة العربية السعودية. ويسعى الطرفان أولاً إلى تسوية أي خلاف ودياً خلال 15 يوم عمل من تاريخ الإشعار الكتابي، فإن تعذر ذلك فيكون الاختصاص للمحاكم المختصة داخل المملكة العربية السعودية."),
        _clause(13, "أحكام عامة", "تمثل هذه الاتفاقية كامل التفاهم بين الطرفين، ولا تعدل إلا كتابة وبموافقتهما. وإذا أصبح أي بند غير نافذ يبقى باقي الاتفاق نافذاً بالقدر الذي يسمح به النظام، ولكل طرف نسخة للعمل بموجبها."),
    ])

    css = """
    @page { size:A4; margin:10mm 12mm 11mm; }
    html, body { margin:0; padding:0; }
    body { font-family:Arial,'Noto Sans Arabic',sans-serif; color:#132a52; direction:rtl; background:#fff; font-size:10.5pt; }
    .page { page-break-after:always; }
    .page:last-child { page-break-after:auto; }
    .brand { width:100%; border-collapse:collapse; margin:0 0 8px; border-bottom:2px solid #1550bf; }
    .brand td { padding:2px 0 5px; vertical-align:middle; }
    .brand-logo { width:122px; height:auto; display:block; }
    .page-label { text-align:left; color:#60769c; font-size:9pt; }
    h1 { margin:3px 0 2px; text-align:center; color:#0c43a5; font-size:22pt; }
    .subtitle { text-align:center; font-weight:bold; font-size:10.5pt; margin-bottom:7px; }
    .meta { width:100%; border-collapse:collapse; margin-bottom:7px; }
    .meta td { width:50%; border:1px solid #c8d7ef; background:#f4f7fc; padding:6px 8px; text-align:center; }
    .section-title { background:#0c43a5; color:#fff; padding:5px 8px; font-weight:bold; font-size:11.5pt; margin:6px 0 4px; }
    .card { border:1px solid #c8d7ef; padding:6px 8px; margin-bottom:5px; }
    .card h2 { color:#0c43a5; font-size:11pt; margin:0 0 4px; }
    table.data { width:100%; border-collapse:collapse; font-size:9pt; }
    table.data th, table.data td { border:1px solid #d6deeb; padding:3px 5px; vertical-align:top; }
    table.data th { width:31%; background:#f5f7fb; color:#173d7d; }
    .intro, .manual-note { border:1px solid #c8d7ef; padding:6px 8px; line-height:1.55; margin-bottom:5px; }
    .manual-note { background:#f4f7fc; border-right:4px solid #1550bf; }
    .clause { border-bottom:1px solid #d5deed; padding:5px 0 6px; page-break-inside:avoid; }
    .clause h3 { color:#0c43a5; margin:0 0 2px; font-size:11pt; }
    .clause p { margin:0; color:#263c61; font-size:9.2pt; line-height:1.48; }
    .approval-table { width:100%; border-collapse:collapse; margin-top:6px; }
    .approval-table td { width:50%; border:1px solid #c8d7ef; padding:7px; vertical-align:top; }
    .approval-table h3 { margin:0 0 5px; color:#0c43a5; font-size:11pt; }
    .approval-line { margin:3px 0; font-size:9.3pt; line-height:1.5; }
    .activation { margin-top:6px; padding:6px 8px; background:#eef4ff; border:1px solid #b9cff0; color:#0c43a5; font-weight:bold; font-size:9.5pt; }
    .footer { margin-top:7px; border-top:1px solid #d6deeb; padding-top:3px; color:#62779b; font-size:8pt; }
    .ltr { direction:ltr; unicode-bidi:embed; display:inline-block; }
    """

    agreement = _ltr(data.agreement_number)
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{css}</style></head><body>
<section class="page">
  <table class="brand"><tr><td><img class="brand-logo" src="pakgat-logo.jpg" alt="Pakgat"></td><td class="page-label">اتفاقية شراكة تجارية</td></tr></table>
  <h1>اتفاقية شراكة</h1>
  <div class="subtitle">لترويج وبيع العروض والقسائم الإلكترونية بين شركة تام العاصمة التجارية (Pakgat) والتاجر</div>
  <table class="meta"><tr><td><b>رقم الاتفاقية</b><br>{agreement}</td><td><b>التاريخ</b><br>{_ltr(data.agreement_date)}</td></tr></table>
  <div class="section-title">أولاً: أطراف الاتفاقية</div>
  <div class="card"><h2>الطرف الأول: شركة تام العاصمة التجارية – المالكة لمنصة Pakgat.com</h2><table class="data">
    {_row('السجل التجاري','1009100740',ltr=True)}{_row('الرقم الضريبي','312531659100003',ltr=True)}{_row('IBAN','SA1710000026700000717001',ltr=True)}{_row('الموقع الإلكتروني','https://pakgat.com',ltr=True)}
  </table></div>
  <div class="card"><h2>الطرف الثاني: التاجر</h2><table class="data">{merchant_rows}</table></div>
  <div class="section-title">ثانياً: التمهيد</div>
  <div class="intro">حيث إن الطرف الأول يدير منصة إلكترونية متخصصة في تسويق وبيع العروض والباقات والقسائم الإلكترونية، ويرغب الطرف الثاني في عرض خدماته أو منتجاته عبر المنصة للوصول إلى عملاء جدد، فقد اتفق الطرفان – وهما بكامل أهليتهما المعتبرة – على ما يلي، ويعد هذا التمهيد جزءاً لا يتجزأ من الاتفاقية.</div>
  <div class="manual-note"><b>إجراء التوقيع والاعتماد:</b> يراجع التاجر هذه الاتفاقية داخل بوابة Pakgat ويؤكد موافقته عليها باستخدام رمز تحقق OTP مستقل يرسل إلى رقم الجوال المسجل. نجاح رمز التحقق يعد موافقة إلكترونية موثقة على رقم الاتفاقية المعروض، ثم ينتقل الطلب إلى مراجعة Pakgat النهائية. لا يتم تفعيل حساب التاجر تلقائياً.</div>
  <div class="footer">بكجات | Pakgat.com | {agreement}</div>
</section>
<section class="page">
  <div class="section-title">ثالثاً: الشروط والأحكام (1)</div>
  {clauses_1}
  <div class="footer">بكجات | Pakgat.com | {agreement}</div>
</section>
<section class="page">
  <div class="section-title">ثالثاً: الشروط والأحكام (2)</div>
  {clauses_2}
  <div class="section-title">رابعاً: الموافقة الإلكترونية والاعتماد النهائي</div>
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
  <div class="footer">بكجات | Pakgat.com | {agreement}</div>
</section>
</body></html>'''


def render_contract_pdf_otp(data: contract_pdf.ContractData, *, converter=contract_pdf._libreoffice_converter) -> bytes:
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        source_path = root / "merchant-agreement.html"
        source_path.write_text(build_contract_html_otp(data), encoding="utf-8")

        # LibreOffice renders a normal local JPEG much more reliably than a large data URI.
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
