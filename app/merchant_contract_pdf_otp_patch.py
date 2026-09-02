"""Adjust the branded merchant contract copy for OTP acceptance.

This intentionally leaves the existing three-page visual renderer untouched and
only changes signing/approval language.  Loaded after merchant_contract_otp.
"""
from __future__ import annotations

import re

from app import merchant_contract_pdf as contract_pdf

_original_build_contract_html = contract_pdf.build_contract_html


def build_contract_html_otp(data: contract_pdf.ContractData) -> str:
    html = _original_build_contract_html(data)
    html = re.sub(
        r'<div class="manual-note">.*?</div>',
        '<div class="manual-note"><b>إجراء التوقيع والاعتماد:</b> يراجع التاجر هذه الاتفاقية داخل بوابة Pakgat ويؤكد موافقته عليها باستخدام رمز تحقق OTP مستقل يرسل إلى رقم الجوال المسجل. نجاح رمز التحقق يعد موافقة إلكترونية موثقة على رقم الاتفاقية المعروض، ثم ينتقل الطلب إلى مراجعة Pakgat النهائية. لا يتم تفعيل حساب التاجر تلقائياً.</div>',
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace(
        'ثالثاً: الشروط والأحكام (2) والتوقيعات',
        'ثالثاً: الشروط والأحكام (2) والموافقة الإلكترونية',
    )
    html = html.replace(
        '<div class="section-title">رابعاً: توقيع وختم الطرفين</div>',
        '<div class="section-title">رابعاً: الموافقة الإلكترونية والاعتماد النهائي</div>',
    )
    signature_html = f'''<div class="signature-wrap">
      <div class="signature"><h3>الطرف الأول - شركة تام العاصمة التجارية (Pakgat)</h3>
        <div class="line">الاسم: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_NAME)}</div>
        <div class="line">الصفة: {contract_pdf._e(contract_pdf.PAKGAT_SIGNER_TITLE)}</div>
        <div class="line">الاعتماد: قرار Pakgat النهائي بعد مراجعة الطلب</div>
        <div class="line">الحالة: لا يصبح الحساب Active إلا بعد الاعتماد</div>
      </div>
      <div class="signature"><h3>الطرف الثاني - التاجر</h3>
        <div class="line">الاسم: {contract_pdf._e(data.representative_name)}</div>
        <div class="line">الصفة: {contract_pdf._e(data.representative_title)}</div>
        <div class="line">الجوال: {contract_pdf._e(data.contact_phone)}</div>
        <div class="line">الموافقة: إلكترونياً عبر OTP مخصص لهذه الاتفاقية</div>
        <div class="line">رقم الاتفاقية: {contract_pdf._e(data.agreement_number)}</div>
      </div>
    </div>'''
    html = re.sub(
        r'<div class="signature-wrap">.*?</div></div>\s*<div class="activation">',
        signature_html + '<div class="activation">',
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace(
        'حالة التفعيل: توقيع العقد وختمه لا يفعّل حساب التاجر تلقائياً. يصبح الحساب Active فقط بعد الموافقة النهائية من Pakgat على طلب التسجيل.',
        'حالة التفعيل: نجاح OTP يثبت موافقة التاجر على الاتفاقية ولا يفعّل الحساب تلقائياً. يصبح الحساب Active فقط بعد الموافقة النهائية من Pakgat على طلب التسجيل.',
    )
    return html


contract_pdf.build_contract_html = build_contract_html_otp

__all__ = ["build_contract_html_otp"]
