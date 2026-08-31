"""Official merchant-facing brand assets for the Pakgat onboarding page.

Presentation only: keep the onboarding flow unchanged while replacing the
embedded Pakgat logo with the official Salla-hosted asset and showing the
official Nafath image in the trust section.
"""

from __future__ import annotations

import re

from app import merchant_onboarding as onboarding
from app import merchant_onboarding_ui as ui


PAKGAT_LOGO_URL = (
    "https://cdn.files.salla.network/theme/650097422/"
    "d2d7a36c-08de-4b6b-a8be-80490dbc0fc8-original.webp"
)
NAFATH_IMAGE_URL = (
    "https://cdn.files.salla.network/other/650097422/"
    "34e46b26-5825-429a-8567-c29175cbeb44-original.webp"
)

_ASSET_CSS = f"""
/* Official Pakgat / Nafath assets */
.brand img[src='{PAKGAT_LOGO_URL}']{{
  width:132px!important;
  max-width:34vw;
  max-height:60px;
  object-fit:contain;
  display:block;
}}
.nafath-official{{
  margin-top:14px;
  display:flex;
  align-items:center;
  justify-content:flex-start;
}}
.nafath-official img{{
  display:block;
  width:180px;
  max-width:72%;
  height:auto;
  object-fit:contain;
  background:#fff;
  border:1px solid #cfe9e2;
  border-radius:13px;
  padding:9px 12px;
  box-shadow:0 8px 20px rgba(7,128,111,.08);
}}
@media(max-width:700px){{
  .brand img[src='{PAKGAT_LOGO_URL}']{{width:108px!important;max-height:50px}}
  .nafath-official img{{width:155px;max-width:78%}}
}}
"""


def apply_official_brand_assets(html: str) -> str:
    """Return the rendered registration page with official public brand assets."""
    rendered = str(html or "")

    embedded_logo = getattr(ui, "LOGO", "")
    if embedded_logo:
        rendered = rendered.replace(embedded_logo, PAKGAT_LOGO_URL)

    if _ASSET_CSS not in rendered:
        if "</style>" in rendered:
            rendered = rendered.replace("</style>", _ASSET_CSS + "</style>", 1)
        elif "</head>" in rendered:
            rendered = rendered.replace("</head>", f"<style>{_ASSET_CSS}</style></head>", 1)

    if NAFATH_IMAGE_URL not in rendered:
        nafath_block = (
            "<div class='nafath-official'>"
            f"<img src='{NAFATH_IMAGE_URL}' alt='النفاذ الوطني الموحد - نفاذ' loading='lazy'>"
            "</div>"
        )

        # Prefer replacing the existing small Nafath badge in the lower trust card.
        pattern = re.compile(
            r"<(?P<tag>[a-zA-Z0-9]+)(?P<attrs>[^>]*\bclass=['\"][^'\"]*\bnafath\b[^'\"]*['\"][^>]*)>.*?</(?P=tag)>",
            re.DOTALL,
        )
        rendered, count = pattern.subn(nafath_block, rendered, count=1)

        # Fallback for future copy/layout changes: place the image immediately
        # below the existing identity-trust heading.
        if count == 0:
            heading = "<h3>هوية موثوقة</h3>"
            if heading in rendered:
                rendered = rendered.replace(heading, heading + nafath_block, 1)
            elif "</main>" in rendered:
                rendered = rendered.replace(
                    "</main>",
                    "<section class='wrap' style='padding:0 0 28px'>"
                    "<div class='secure' style='border:1px solid #d7eee8;border-radius:18px;padding:20px'>"
                    "<h3 style='margin-top:0;color:#07806f'>التحقق عبر نفاذ</h3>"
                    + nafath_block
                    + "</div></section></main>",
                    1,
                )

    return rendered


_original_register_page = onboarding._register_page


def register_page_with_official_assets(challenge_token: str = "", message: str = "") -> str:
    return apply_official_brand_assets(_original_register_page(challenge_token, message))


onboarding._register_page = register_page_with_official_assets


__all__ = [
    "PAKGAT_LOGO_URL",
    "NAFATH_IMAGE_URL",
    "apply_official_brand_assets",
    "register_page_with_official_assets",
]
