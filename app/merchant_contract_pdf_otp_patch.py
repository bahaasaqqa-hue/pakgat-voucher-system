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


def _pair_row(label1: str, value1: str, label2: str, value2: str, *, ltr1: bool = False, ltr2: bool = False) -> str:
    return (
        '<tr>'
        f'<th>{contract_pdf._e(label1)}</th><td>{_value(value1, ltr=ltr1)}</td>'
        f'<th>{contract_pdf._e(label2)}</th><td>{_value(value2, ltr=ltr2)}</td>'
        '</tr>'
    )


def _clause(number: int, title: str, body: str) -> str:
    return (
        '<div class="clause">'
        f'<h3>{number}. {contract_pdf._e(title)}</h3>'
        f'<p>{contract_pdf._e(body)}</p>'
        '</div>'
    )


def _clauses() -> dict[int, str]:
    content = {
        1: ("التزامات الطرف الأول (Pakgat)", "تتولى Pakgat تصميم ونشر وتسويق العروض عبر المنصة، وإصدار القسائم الإلكترونية وتوفير نظام التحقق منها، وتحصيل قيمة الطلبات وتحويل صافي مستحقات التاجر وفق البيانات المالية المعتمدة، مع تقديم دعم المنصة. ولا تضمن Pakgat عدداً محدداً من المبيعات أو العملاء."),
        2: ("التزامات الطرف الثاني (التاجر)", "يلتزم التاجر بتقديم الخدمة أو المنتج بالمواصفات والسعر والشروط المعتمدة، وقبول القسائم الصالحة دون رسوم غير معلنة، وضمان صحة بياناته وأسعاره وتراخيصه والمحافظة على وسائل التحقق، ويتحمل المسؤولية النظامية عن جودة ما يقدمه وأي مطالبات ناشئة عنه."),
        3: ("القسائم الإلكترونية", "تصدر لكل عملية شراء قسيمة برمز تحقق فريد تستخدم لمرة واحدة، وتعد مستخدمة بعد اعتمادها عبر النظام، ولا يجوز إعادة استخدامها أو قبولها بعد انتهاء صلاحيتها إلا باستثناء مكتوب من Pakgat لحماية حقوق العميل."),
        4: ("التسوية المالية", "تحول Pakgat صافي مستحقات التاجر إلى الآيبان المسجل وفق دورة التسوية المعتمدة بعد خصم المبالغ المستردة والإلغاءات والأخطاء المحاسبية والرسوم المتفق عليها. ويعد كشف التسوية أساساً للمراجعة، ويكون الاعتراض خلال 7 أيام عمل من إرساله."),
        5: ("الإلغاء والاسترجاع وحقوق العملاء", "تخضع طلبات الإلغاء والاستبدال والاسترجاع لسياسات Pakgat المعلنة وبما يتفق مع الأنظمة. وإذا ألغي الطلب أو تعذر على التاجر تقديم الخدمة أو المنتج لسبب يعود إليه، يلتزم بمعالجة حقوق العملاء وإعادة المبالغ المستحقة أو تنفيذ البديل الذي تعتمده Pakgat."),
        6: ("التسويق والملكية الفكرية", "تبقى حقوق الملكية الفكرية والعلامات التجارية لكل طرف ملكاً له. ويمنح التاجر Pakgat ترخيصاً غير حصري ومجانياً طوال مدة التعاون لاستخدام اسمه وشعاره وصوره ومواد العروض لأغراض إعداد الصفحات والتسويق والإعلان في قنوات Pakgat وشركائها دون نقل ملكية تلك الحقوق."),
        7: ("السرية وحماية البيانات", "يلتزم الطرفان بسرية المعلومات التجارية والمالية وبيانات العملاء وعدم استخدامها إلا بالقدر اللازم لتنفيذ الاتفاقية أو وفق ما تتطلبه الأنظمة، واتخاذ التدابير المناسبة لحماية البيانات الواقعة تحت سيطرة كل طرف وعدم مشاركتها مع غير المخولين."),
        8: ("حدود الصلاحيات والتعديلات", "لا يعتد بأي تعديل على الشروط التجارية أو الخصومات أو الالتزامات أو الوعود بالمبيعات أو الميزانيات الإعلانية أو الحصرية أو آجال السداد إلا بموافقة كتابية صادرة من Pakgat. ولا يجوز لأي شخص غير مفوض قبض مبالغ باسم Pakgat أو إبرام التزام مالي أو قانوني باسمها."),
        9: ("عدم الحصرية", "ما لم يتفق الطرفان كتابة على خلاف ذلك، تعد هذه الاتفاقية غير حصرية، ويجوز لكل طرف التعامل مع أطراف أخرى شريطة عدم استخدام المعلومات السرية للطرف الآخر أو الإخلال بالطلبات والعروض القائمة وحقوق العملاء."),
        10: ("مدة الاتفاقية وإنهاؤها", "تسري الاتفاقية من تاريخ توقيعها وتستمر حتى انتهاء العروض النشطة وتسوية الالتزامات المالية المتعلقة بها. ويجوز لأي من الطرفين إنهاؤها عند الإخلال الجوهري أو مخالفة الأنظمة أو توقف النشاط أو إساءة استخدام المنصة، مع بقاء حقوق العملاء والمستحقات والالتزامات السابقة نافذة حتى تسويتها."),
        11: ("القوة القاهرة", "لا يتحمل أي من الطرفين مسؤولية التأخير أو عدم التنفيذ الناتج مباشرة عن ظروف خارجة عن الإرادة لا يمكن توقعها أو دفعها بصورة معقولة، مع التزام الطرف المتأثر بإشعار الطرف الآخر واتخاذ ما يمكن لتقليل الأثر."),
        12: ("القانون والاختصاص", "تخضع هذه الاتفاقية لأنظمة المملكة العربية السعودية. ويسعى الطرفان أولاً إلى تسوية أي خلاف ودياً خلال 15 يوم عمل من تاريخ الإشعار الكتابي، فإن تعذر ذلك فيكون الاختصاص للمحاكم المختصة داخل المملكة العربية السعودية."),
        13: ("أحكام عامة", "تمثل هذه الاتفاقية كامل التفاهم بين الطرفين، ولا تعدل إلا كتابة وبموافقتهما. وإذا أصبح أي بند غير نافذ يبقى باقي الاتفاق نافذاً بالقدر الذي يسمح به النظام، ولكل طرف نسخة للعمل بموجبها."),
    }
    return {number: _clause(number, title, body) for number, (title, body) in content.items()}


def build_contract_html_otp(data: contract_pdf.ContractData) -> str:
    c = _clauses()
    agreement = _ltr(data.agreement_number)

    merchant_grid = "".join([
        _pair_row("اسم المنشأة", data.legal_name, "السجل التجاري / الرقم الموحد", data.commercial_registration, ltr2=True),
        _pair_row("النشاط", data.activity, "الرقم الضريبي", data.tax_number, ltr2=True),
        _pair_row("البنك", data.bank_name, "IBAN", data.iban, ltr2=True),
        _pair_row("العنوان", data.national_address, "رقم الجوال", data.contact_phone, ltr2=True),
        _pair_row("البريد الإلكتروني", data.contact_email, "الموقع الإلكتروني", data.website or "لا يوجد", ltr1=True, ltr2=True),
        _pair_row("اسم الممثل", data.representative_name, "صفة الممثل", data.representative_title),
    ])

    css = """
    @page { size:A4; margin:8mm 10mm 9mm; }
    html,body { margin:0; padding:0; }
    body { font-family:Arial,'Noto Sans Arabic',sans-serif; direction:rtl; color:#10264e; background:#fff; font-size:9pt; }
    .page { page-break-after:always; }
    .page:last-child { page-break-after:auto; }
    table { border-collapse:collapse; }
    .brand { width:100%; margin:0 0 3mm; border-bottom:2px solid #1450bd; }
    .brand td { padding:1mm 0 2mm; vertical-align:middle; }
    .brand-logo { width:86px; height:auto; display:block; }
    .page-label { text-align:left; color:#6a7d9c; font-size:8pt; }
    h1 { margin:1mm 0 .5mm; text-align:center; color:#0d45a6; font-size:20pt; }
    .subtitle { text-align:center; font-weight:bold; font-size:9pt; margin-bottom:2mm; }
    .meta { width:100%; table-layout:fixed; margin-bottom:2mm; }
    .meta td { width:50%; border:1px solid #c7d6ed; background:#f4f7fc; padding:1.5mm 2mm; text-align:center; }
    .section-title { background:#0d45a6; color:white; font-weight:bold; font-size:10.5pt; padding:1.2mm 2mm; margin:1.5mm 0 1mm; }
    .party-title { color:#0d45a6; font-size:10pt; font-weight:bold; margin:1mm 0; }
    .party-table,.merchant-grid { width:100%; table-layout:fixed; font-size:8.2pt; margin-bottom:1.5mm; }
    .party-table th,.party-table td,.merchant-grid th,.merchant-grid td { border:1px solid #d2dceb; padding:1mm 1.4mm; vertical-align:middle; }
    .party-table th,.merchant-grid th { background:#f5f7fb; color:#173d7d; width:18%; font-weight:bold; }
    .merchant-grid td { width:32%; }
    .intro,.manual-note { border:1px solid #c7d6ed; padding:1.4mm 2mm; line-height:1.42; margin-bottom:1.2mm; font-size:8.3pt; }
    .manual-note { background:#f4f7fc; border-right:3px solid #1450bd; }
    .clause-columns { width:100%; table-layout:fixed; direction:rtl; }
    .clause-columns td { width:50%; vertical-align:top; padding:0 2mm; }
    .clause-columns td:first-child { border-left:1px solid #d8e0ec; }
    .clause { border-bottom:1px solid #d5deed; padding:1.4mm 0 1.7mm; page-break-inside:avoid; }
    .clause h3 { color:#0d45a6; margin:0 0 .7mm; font-size:9.6pt; }
    .clause p { margin:0; color:#283d61; font-size:8.1pt; line-height:1.4; }
    .approval-table { width:100%; table-layout:fixed; margin-top:1.5mm; page-break-inside:avoid; }
    .approval-table td { width:50%; border:1px solid #c7d6ed; padding:2mm; vertical-align:top; }
    .approval-table h3 { margin:0 0 1mm; color:#0d45a6; font-size:9.6pt; }
    .approval-line { margin:.7mm 0; font-size:8.2pt; line-height:1.35; }
    .activation { margin-top:1.5mm; padding:1.5mm 2mm; background:#edf4ff; border:1px solid #b8cdef; color:#0d45a6; font-weight:bold; font-size:8.3pt; page-break-inside:avoid; }
    .footer { margin-top:2mm; border-top:1px solid #d6deeb; padding-top:.8mm; color:#657999; font-size:7.2pt; text-align:center; }
    .ltr { direction:ltr; unicode-bidi:embed; display:inline-block; }
    """

    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{css}</style></head><body>
<section class="page">
  <table class="brand"><tr><td><img class="brand-logo" src="pakgat-logo.jpg" alt="Pakgat"></td><td class="page-label">اتفاقية شراكة تجارية</td></tr></table>
  <h1>اتفاقية شراكة</h1>
  <div class="subtitle">لترويج وبيع العروض والقسائم الإلكترونية بين شركة تام العاصمة التجارية (Pakgat) والتاجر</div>
  <table class="meta"><tr><td><b>رقم الاتفاقية</b><br>{agreement}</td><td><b>التاريخ</b><br>{_ltr(data.agreement_date)}</td></tr></table>
  <div class="section-title">أولاً: أطراف الاتفاقية</div>
  <div class="party-title">الطرف الأول: شركة تام العاصمة التجارية – المالكة لمنصة Pakgat.com</div>
  <table class="party-table">
    {_pair_row('السجل التجاري','1009100740','الرقم الضريبي','312531659100003',ltr1=True,ltr2=True)}
    {_pair_row('IBAN','SA1710000026700000717001','الموقع الإلكتروني','https://pakgat.com',ltr1=True,ltr2=True)}
  </table>
  <div class="party-title">الطرف الثاني: التاجر</div>
  <table class="merchant-grid">{merchant_grid}</table>
  <div class="section-title">ثانياً: التمهيد</div>
  <div class="intro">حيث إن الطرف الأول يدير منصة إلكترونية متخصصة في تسويق وبيع العروض والباقات والقسائم الإلكترونية، ويرغب الطرف الثاني في عرض خدماته أو منتجاته عبر المنصة للوصول إلى عملاء جدد، فقد اتفق الطرفان – وهما بكامل أهليتهما المعتبرة – على ما يلي، ويعد هذا التمهيد جزءاً لا يتجزأ من الاتفاقية.</div>
  <div class="manual-note"><b>إجراء التوقيع والاعتماد:</b> يراجع التاجر هذه الاتفاقية داخل بوابة Pakgat ويؤكد موافقته عليها باستخدام رمز تحقق OTP مستقل يرسل إلى رقم الجوال المسجل. نجاح رمز التحقق يعد موافقة إلكترونية موثقة على رقم الاتفاقية المعروض، ثم ينتقل الطلب إلى مراجعة Pakgat النهائية. لا يتم تفعيل حساب التاجر تلقائياً.</div>
  <div class="footer">بكجات | Pakgat.com | {agreement}</div>
</section>
<section class="page">
  <div class="section-title">ثالثاً: الشروط والأحكام (1)</div>
  <table class="clause-columns"><tr><td>{c[1]}{c[2]}{c[3]}{c[4]}</td><td>{c[5]}{c[6]}{c[7]}</td></tr></table>
  <div class="footer">بكجات | Pakgat.com | {agreement}</div>
</section>
<section class="page">
  <div class="section-title">ثالثاً: الشروط والأحكام (2)</div>
  <table class="clause-columns"><tr><td>{c[8]}{c[9]}{c[10]}</td><td>{c[11]}{c[12]}{c[13]}</td></tr></table>
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


def _logo_bytes() -> bytes:
    uri = contract_pdf._logo_data_uri()
    try:
        return base64.b64decode(uri.split(',', 1)[1])
    except Exception:
        raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None


def render_contract_pdf_otp(data: contract_pdf.ContractData, *, converter=None) -> bytes:
    converter = converter or contract_pdf._libreoffice_converter
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        (root / "pakgat-logo.jpg").write_bytes(_logo_bytes())
        source_path = root / "merchant-agreement.html"
        source_path.write_text(build_contract_html_otp(data), encoding="utf-8")
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
