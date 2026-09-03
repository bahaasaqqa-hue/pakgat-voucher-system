"""Read-only Google Search Console metrics for Pakgat AI Company."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request as UrlRequest, urlopen

from sqlalchemy import DateTime, Float, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.google_analytics import _metadata_access_token


SITE_URL = core.env("GOOGLE_SEARCH_CONSOLE_SITE_URL", "sc-domain:pakgat.com")
SERVICE_ACCOUNT = core.env("GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT") or core.env("GOOGLE_ANALYTICS_SERVICE_ACCOUNT")


class SearchConsoleSnapshot(core.Base):
    __tablename__ = "google_search_console_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_url: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    top_queries_json: Mapped[str] = mapped_column(String(12000), default="[]")
    top_pages_json: Mapped[str] = mapped_column(String(12000), default="[]")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class SearchConsoleSyncError(RuntimeError):
    pass


def parse_search_analytics(payload: dict) -> dict:
    rows = payload.get("rows") or []
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    row = rows[0]
    return {
        "clicks": max(0, int(float(row.get("clicks") or 0))),
        "impressions": max(0, int(float(row.get("impressions") or 0))),
        "ctr": max(0.0, float(row.get("ctr") or 0)),
        "position": max(0.0, float(row.get("position") or 0)),
    }


def parse_dimension_rows(payload: dict, limit: int = 10) -> list[dict]:
    result = []
    for row in (payload.get("rows") or [])[:limit]:
        keys = row.get("keys") or []
        result.append({
            "value": str(keys[0] if keys else "")[:500],
            "clicks": max(0, int(float(row.get("clicks") or 0))),
            "impressions": max(0, int(float(row.get("impressions") or 0))),
            "ctr": round(max(0.0, float(row.get("ctr") or 0)) * 100, 2),
            "position": round(max(0.0, float(row.get("position") or 0)), 2),
        })
    return result


def display_page_label(value: str) -> str:
    path = unquote(urlsplit(str(value or "")).path or "/").rstrip("/") or "/"
    if path == "/":
        return "الصفحة الرئيسية"
    if path == "/ar":
        return "الصفحة العربية"
    if path == "/en":
        return "الصفحة الإنجليزية"
    return "مسار: " + path[:90]


def _impersonated_token(service_account: str, source_token: str) -> str:
    url = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/" + quote(service_account, safe="") + ":generateAccessToken"
    body = json.dumps({"delegates": [], "scope": ["https://www.googleapis.com/auth/webmasters.readonly"], "lifetime": "3600s"}).encode()
    request = UrlRequest(url, data=body, headers={"Authorization": f"Bearer {source_token}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            token = str(json.loads(response.read().decode()).get("accessToken") or "")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise SearchConsoleSyncError("SearchConsoleAuthenticationError") from exc
    if not token:
        raise SearchConsoleSyncError("SearchConsoleAuthenticationError")
    return token


def _access_token() -> str:
    source = _metadata_access_token()
    return _impersonated_token(SERVICE_ACCOUNT, source) if SERVICE_ACCOUNT else source


def fetch_search_analytics(site_url: str, dimensions: list[str] | None = None) -> dict:
    if not site_url:
        raise SearchConsoleSyncError("SearchConsoleSiteUrlError")
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=27)
    body = {"startDate": start_date.isoformat(), "endDate": end_date.isoformat(), "type": "web", "rowLimit": 10}
    if dimensions:
        body["dimensions"] = dimensions
    request = UrlRequest(
        "https://searchconsole.googleapis.com/webmasters/v3/sites/" + quote(site_url, safe="") + "/searchAnalytics/query",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise SearchConsoleSyncError("SearchConsolePermissionError") from exc
        raise SearchConsoleSyncError("SearchConsoleAPIError") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise SearchConsoleSyncError("SearchConsoleAPIError") from exc


def latest_snapshot(db: Session, site_url: str | None = None) -> Optional[SearchConsoleSnapshot]:
    stmt = select(SearchConsoleSnapshot)
    if site_url:
        stmt = stmt.where(SearchConsoleSnapshot.site_url == site_url)
    return db.scalar(stmt.order_by(SearchConsoleSnapshot.fetched_at.desc()).limit(1))


def sync_snapshot(db: Session, site_url: str, *, fetcher: Callable[[str, list[str] | None], dict] = fetch_search_analytics) -> SearchConsoleSnapshot:
    site_url = str(site_url or "").strip()
    if not site_url:
        raise SearchConsoleSyncError("SearchConsoleSiteUrlError")
    aggregate = parse_search_analytics(fetcher(site_url, None))
    queries = parse_dimension_rows(fetcher(site_url, ["query"]))
    pages = parse_dimension_rows(fetcher(site_url, ["page"]))
    row = db.scalar(select(SearchConsoleSnapshot).where(SearchConsoleSnapshot.site_url == site_url))
    if row is None:
        row = SearchConsoleSnapshot(site_url=site_url)
        db.add(row)
    row.clicks, row.impressions, row.ctr, row.position = aggregate["clicks"], aggregate["impressions"], aggregate["ctr"], aggregate["position"]
    row.top_queries_json, row.top_pages_json = json.dumps(queries, ensure_ascii=False), json.dumps(pages, ensure_ascii=False)
    row.fetched_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(row)
    return row


def refresh_if_stale(db: Session, site_url: str, max_age: timedelta = timedelta(minutes=30)) -> SearchConsoleSnapshot:
    row = latest_snapshot(db, site_url)
    if row:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched <= max_age:
            return row
    return sync_snapshot(db, site_url)


def connection_state(db: Session) -> tuple[str, str]:
    if not SITE_URL:
        return "Needs Integration", "Search Console site URL is missing"
    row = latest_snapshot(db, SITE_URL)
    if row is None:
        return "Needs Integration", "Site configured; awaiting first successful read"
    return "Connected", f"Search Console read-only · last read {core.fmt_dt(row.fetched_at)}"
