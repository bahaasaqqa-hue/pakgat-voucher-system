"""Safety fix for the compact opportunities dashboard wrapper.

The first compact implementation used broad regular expressions that could span
multiple dashboard sections while trying to remove the old dispatch box. This
patch replaces that helper with marker-bounded section replacement so Sales,
Salla, Sources, Alerts, Tasks and every other dashboard section remain visible.
"""

from app import ai_company_opportunity_compact as compact


def _section_bounds(html: str, marker: str):
    """Return the nearest card <section> containing marker, without spanning cards."""
    marker_pos = html.find(marker)
    if marker_pos < 0:
        return None

    start = html.rfind("<section class='card'", 0, marker_pos)
    if start < 0:
        return None

    end_marker = "</section>"
    end = html.find(end_marker, marker_pos)
    if end < 0:
        return None
    return start, end + len(end_marker)


def safe_replace_dashboard_opportunity_sections(html: str, section: str) -> str:
    # Replace only the original large opportunity card.
    bounds = _section_bounds(html, "الفرص الجديدة لـ Pakgat")
    if bounds:
        start, end = bounds
        html = html[:start] + section + html[end:]
    else:
        html = html.replace("</main>", section + "</main>", 1)

    # Remove only the standalone dispatch card, not everything before it.
    bounds = _section_bounds(html, "Opportunity Dispatch · المندوبون")
    if bounds:
        start, end = bounds
        html = html[:start] + html[end:]

    return html


compact._replace_dashboard_opportunity_sections = safe_replace_dashboard_opportunity_sections
