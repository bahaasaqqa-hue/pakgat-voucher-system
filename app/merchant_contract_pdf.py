"""Build Pakgat's branded manual-signing merchant agreement and render it as PDF."""
from __future__ import annotations

import base64
import html
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

PAKGAT_SIGNER_NAME = "بهاء السقا"
PAKGAT_SIGNER_TITLE = "مدير تطوير الأعمال"
PAKGAT_SIGNER_PHONE = "0504161514"

# Kept for compatibility with callers/tests that import the old constants.
TEMPLATE_PARTS = ()
TEMPLATE_SHA256 = ""


class ContractRenderError(RuntimeError):
    """Safe contract-generation error."""


@dataclass(frozen=True)
class ContractData:
    agreement_number: str
    agreement_date: str
    legal_name: str
    commercial_registration: str
    activity: str
    tax_number: str
    bank_name: str
    iban: str
    national_address: str
    contact_phone: str
    contact_email: str
    website: str
    representative_name: str
    representative_title: str


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _e(value: str) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _logo_data_uri() -> str:
    path = _asset_dir() / "pakgat_contract_logo.b64"
    if not path.is_file():
        raise ContractRenderError("Pakgat contract logo is missing")
    try:
        payload = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    except Exception:
        raise ContractRenderError("Pakgat contract logo is invalid") from None
    if not payload.startswith(b"\xff\xd8\xff"):
        raise ContractRenderError("Pakgat contract logo is invalid")
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def _row(label: str, value: str) -> str:
    return f'<tr><th>{_e(label)}</th><td>{_e(value)}</td></tr>'


def _clause(number: int, title: str, body: str) -> str:
    return (
        '<div class="clause">'
        f'<h3>{number}. {_e(title)}</h3>'
        f'<p>{_e(body)}</p>'
        '</div>'
    )


def build_contract_html(data: ContractData) -> str:
    """Return a balanced three-page Arabic RTL contract ready for LibreOffice PDF export."""
    logo = _logo_data_uri()
    merchant_rows = "".join([
        _row("اسم المنشأة", data.legal_name),
        _row("السجل التجاري / الرقم الموحد", data.commercial_registration),
        _row("النشاط", data.activity),
        _row("الرقم الضريبي", data.tax_number),
        _row("البنك", data.bank_name),
        _row("IBAN", data.iban),
        _row("العنوان", data.national_address),
        _row("رقم الجوال", data.contact_phone),
        _row("البريد الإلكتروني", data.contact_email),
        _row("الموقع الإلكتروني", data.website or "لا يوجد"),
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
    @page { size: A4; margin: 10mm 12mm; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Arial, 'Noto Sans Arabic', sans-serif; color:#10234b; background:#fff; direction:rtl; }
    .page { width:100%; min-height:267mm; position:relative; page-break-after:always; padding:2mm 1mm 15mm; }
    .page:last-child { page-break-after:auto; }
    .header { display:flex; align-items:center; justify-content:space-between; border-bottom:2px solid #1746b5; padding-bottom:5px; margin-bottom:8px; }
    .logo { width:120px; height:auto; }
    .page-no { background:#0b3b99; color:#fff; width:30px; height:30px; border-radius:15px; text-align:center; line-height:30px; font-weight:bold; }
    h1 { font-size:24px; color:#0b3b99; margin:6px 0 2px; text-align:center; }
    .subtitle { text-align:center; font-size:13px; font-weight:bold; margin-bottom:8px; }
    .meta { width:100%; border-collapse:separate; border-spacing:5px; margin:5px 0 8px; }
    .meta td { background:#f1f6ff; border:1px solid #c9d8f5; border-radius:8px; padding:7px; text-align:center; font-size:12px; }
    .section-title { background:#0b3b99; color:#fff; padding:6px 10px; border-radius:6px; font-size:14px; font-weight:bold; margin:8px 0 5px; }
    .card { border:1px solid #c9d8f5; border-radius:8px; padding:8px; margin-bottom:7px; background:#fff; }
    .card h2 { color:#0b3b99; font-size:14px; margin:0 0 6px; }
    table.data { width:100%; border-collapse:collapse; font-size:10.5px; }
    table.data th, table.data td { border:1px solid #cbd5e1; padding:4px 6px; }
    table.data th { width:34%; background:#f1f6ff; color:#173b78; }
    .intro { background:#f6f9ff; border-right:4px solid #2f64d6; padding:8px 10px; border-radius:6px; font-size:11px; line-height:1.65; }
    .manual-note { background:#edf4ff; border:1px solid #b9cff7; padding:8px 10px; border-radius:7px; font-size:11px; line-height:1.65; margin-top:7px; }
    .clauses { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
    .clause { border:1px solid #cbd8ee; border-radius:7px; padding:7px 9px; break-inside:avoid; }
    .clause h3 { margin:0 0 4px; color:#0b3b99; font-size:11.5px; }
    .clause p { margin:0; font-size:9.7px; line-height:1.6; color:#263b63; }
    .signature-wrap { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
    .signature { border:1px solid #b9c9e6; border-radius:8px; padding:10px; min-height:150px; }
    .signature h3 { margin:0 0 8px; color:#0b3b99; font-size:13px; }
    .line { border-bottom:1px solid #8ca1c7; height:24px; margin:5px 0; font-size:10px; color:#52698e; }
    .stamp { border:1px dashed #8ca1c7; border-radius:8px; height:58px; margin-top:8px; padding:5px; color:#6d7f9f; font-size:10px; }
    .activation { margin-top:10px; padding:9px; background:#eaf2ff; border:1px solid #a9c3f2; border-radius:7px; font-size:11px; font-weight:bold; color:#0b3b99; }
    .footer { position:absolute; bottom:3mm; right:1mm; left:1mm; border-top:1px solid #d8e1f1; padding-top:4px; font-size:9px; color:#55709e; display:flex; justify-content:space-between; }
    """
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>{css}</style></head><body>
    <section class="page"><div class="header"><img class="logo" src="{logo}"><div class="page-no">1</div></div>
      <h1>اتفاقية شراكة</h1><div class="subtitle">لترويج وبيع العروض والقسائم الإلكترونية بين شركة تام العاصمة التجارية (Pakgat) والتاجر</div>
      <table class="meta"><tr><td><b>رقم الاتفاقية</b><br>{_e(data.agreement_number)}</td><td><b>التاريخ</b><br>{_e(data.agreement_date)}</td></tr></table>
      <div class="section-title">أولاً: أطراف الاتفاقية</div>
      <div class="card"><h2>الطرف الأول: شركة تام العاصمة التجارية – المالكة لمنصة Pakgat.com</h2><table class="data">
        {_row('السجل التجاري','1009100740')}{_row('الرقم الضريبي','312531659100003')}{_row('IBAN','SA1710000026700000717001')}{_row('الموقع الإلكتروني','https://pakgat.com')}
      </table></div>
      <div class="card"><h2>الطرف الثاني: التاجر</h2><table class="data">{merchant_rows}</table></div>
      <div class="section-title">ثانياً: التمهيد</div><div class="intro">حيث إن الطرف الأول يدير منصة إلكترونية متخصصة في تسويق وبيع العروض والباقات والقسائم الإلكترونية، ويرغب الطرف الثاني في عرض خدماته أو منتجاته عبر المنصة للوصول إلى عملاء جدد، فقد اتفق الطرفان – وهما بكامل أهليتهما المعتبرة – على ما يلي، ويعد هذا التمهيد جزءاً لا يتجزأ من الاتفاقية.</div>
      <div class="manual-note"><b>إجراء التوقيع والاعتماد:</b> يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها ثم يرفع النسخة الموقعة عبر منصة Pakgat. بعد مراجعتها، تقوم Pakgat بتوقيع وختم النسخة النهائية ورفعها للتاجر. لا يتم تفعيل حساب التاجر إلا بعد اعتماد Pakgat النهائي.</div>
      <div class="footer"><span>بكجات | Pakgat.com</span><span>{_e(data.agreement_number)}</span></div></section>
    <section class="page"><div class="header"><img class="logo" src="{logo}"><b>ثالثاً: الشروط والأحكام (1)</b><div class="page-no">2</div></div>
      <div class="clauses">{clauses_1}</div><div class="footer"><span>بكجات | Pakgat.com</span><span>{_e(data.agreement_number)}</span></div></section>
    <section class="page"><div class="header"><img class="logo" src="{logo}"><b>ثالثاً: الشروط والأحكام (2) والتوقيعات</b><div class="page-no">3</div></div>
      <div class="clauses">{clauses_2}</div>
      <div class="section-title">رابعاً: توقيع وختم الطرفين</div>
      <div class="signature-wrap"><div class="signature"><h3>الطرف الأول – شركة تام العاصمة التجارية (Pakgat)</h3><div class="line">الاسم: {_e(PAKGAT_SIGNER_NAME)}</div><div class="line">الصفة: {_e(PAKGAT_SIGNER_TITLE)}</div><div class="line">التوقيع:</div><div class="stamp">الختم</div><div class="line">التاريخ:</div></div>
      <div class="signature"><h3>الطرف الثاني – التاجر</h3><div class="line">الاسم: {_e(data.representative_name)}</div><div class="line">الصفة: {_e(data.representative_title)}</div><div class="line">التوقيع:</div><div class="stamp">الختم</div><div class="line">التاريخ:</div></div></div>
      <div class="activation">حالة التفعيل: توقيع العقد وختمه لا يفعّل حساب التاجر تلقائياً. يصبح الحساب Active فقط بعد الموافقة النهائية من Pakgat على طلب التسجيل.</div>
      <div class="footer"><span>بكجات | Pakgat.com</span><span>{_e(data.agreement_number)}</span></div></section>
    </body></html>'''


def build_contract_docx(data: ContractData) -> bytes:
    """Deprecated compatibility shim. The approved contract renderer is HTML -> PDF."""
    raise ContractRenderError("DOCX contract generation has been replaced by the branded PDF renderer")


def _libreoffice_converter(source_path: Path, output_dir: Path) -> None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise ContractRenderError("LibreOffice is not installed on the server")
    profile_dir = output_dir / "libreoffice-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.run([
            executable, f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
            "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
            "--convert-to", "pdf", "--outdir", str(output_dir), str(source_path),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ContractRenderError("Merchant contract PDF conversion failed") from None
    if process.returncode != 0:
        raise ContractRenderError("Merchant contract PDF conversion failed")


def render_contract_pdf(data: ContractData, *, converter=_libreoffice_converter) -> bytes:
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        source_path = root / "merchant-agreement.html"
        source_path.write_text(build_contract_html(data), encoding="utf-8")
        converter(source_path, root)
        pdf_path = root / "merchant-agreement.pdf"
        if not pdf_path.exists():
            raise ContractRenderError("Merchant contract PDF was not generated")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF"):
            raise ContractRenderError("Generated merchant contract PDF is invalid")
        return pdf


__all__ = [
    "TEMPLATE_PARTS", "TEMPLATE_SHA256", "PAKGAT_SIGNER_NAME", "PAKGAT_SIGNER_TITLE",
    "PAKGAT_SIGNER_PHONE", "ContractData", "ContractRenderError", "build_contract_html",
    "build_contract_docx", "render_contract_pdf",
]
