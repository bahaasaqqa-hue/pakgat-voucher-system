"""Scoped typography normalization for authenticated Pakgat AI pages.

Imported immediately before the final admin response middleware. The extension is
appended to the unified admin CSS so legacy inline font sizes cannot make one AI
subpage look materially larger or smaller than another. Public voucher and agent
report pages are intentionally outside this selector.
"""
from app import admin_theme_core


AI_TYPOGRAPHY_CSS = r"""
/* Pakgat AI typography scale — scoped to authenticated AI Company pages only. */
body[data-unified-admin-theme='ai']{font-size:13px!important;line-height:1.6!important}
body[data-unified-admin-theme='ai'] .ai-workspace h1{font-size:22px!important;line-height:1.35!important;font-weight:950!important;margin-top:0!important}
body[data-unified-admin-theme='ai'] .ai-workspace h2{font-size:17px!important;line-height:1.4!important;font-weight:950!important}
body[data-unified-admin-theme='ai'] .ai-workspace h3{font-size:14px!important;line-height:1.45!important;font-weight:900!important}
body[data-unified-admin-theme='ai'] .ai-workspace p,body[data-unified-admin-theme='ai'] .ai-workspace li,body[data-unified-admin-theme='ai'] .ai-workspace label,body[data-unified-admin-theme='ai'] .ai-workspace details,body[data-unified-admin-theme='ai'] .ai-workspace summary{font-size:13px!important}
body[data-unified-admin-theme='ai'] .ai-workspace th{font-size:12px!important;line-height:1.45!important}
body[data-unified-admin-theme='ai'] .ai-workspace td{font-size:12px!important;line-height:1.55!important}
body[data-unified-admin-theme='ai'] .ai-workspace .muted{font-size:11px!important;line-height:1.55!important}
body[data-unified-admin-theme='ai'] .ai-workspace .btn{font-size:12px!important;line-height:1.25!important}
body[data-unified-admin-theme='ai'] .ai-workspace .input{font-size:12px!important;line-height:1.35!important}
body[data-unified-admin-theme='ai'] .ai-workspace .select,body[data-unified-admin-theme='ai'] .ai-workspace select,body[data-unified-admin-theme='ai'] .ai-workspace textarea,body[data-unified-admin-theme='ai'] .ai-workspace input:not([type='checkbox']):not([type='radio']){font-size:12px!important;line-height:1.35!important}
body[data-unified-admin-theme='ai'] .ai-kpi .value{font-size:28px!important;line-height:1.05!important}
body[data-unified-admin-theme='ai'] .ai-big{font-size:28px!important;line-height:1.1!important}
body[data-unified-admin-theme='ai'] .opp-kpi-value{font-size:28px!important;line-height:1.1!important}
body[data-unified-admin-theme='ai'] .ai-panel h2,body[data-unified-admin-theme='ai'] .mc-card h2{font-size:17px!important}
body[data-unified-admin-theme='ai'] .ai-note,body[data-unified-admin-theme='ai'] .ai-approval-meta,body[data-unified-admin-theme='ai'] .opp-meta{font-size:11px!important}
@media(max-width:560px){body[data-unified-admin-theme='ai'] .ai-workspace h1{font-size:20px!important}body[data-unified-admin-theme='ai'] .ai-workspace h2{font-size:16px!important}}
"""


if "Pakgat AI typography scale" not in admin_theme_core.UNIFIED_ADMIN_CSS:
    admin_theme_core.UNIFIED_ADMIN_CSS += AI_TYPOGRAPHY_CSS
