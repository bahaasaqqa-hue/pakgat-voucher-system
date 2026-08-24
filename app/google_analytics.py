"""Read-only GA4 acquisition metrics for Pakgat AI Company.

Authentication uses the GCE instance service account through the metadata
server. No service-account key or Analytics token is stored in the database.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


GA4_PROPERTY_ID = core.env("GOOGLE_ANALYTICS_PROPERTY_ID").strip()
GA4_SERVICE_ACCOUNT = core.env("GOOGLE_ANALYTICS_SERVICE_ACCOUNT").strip()
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
GA4_RUN_REPORT_URL = (
    "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
)


class GoogleAnalyticsSnapshot(core.Base):
    __tablename__ = "google_analytics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    page_views: Mapped[int] = mapped_column(Integer, default=0)
    key_events: Mapped[int] = mapped_column(Integer, default=0)
    period: Mapped[str] = mapped_column(String(40), default="last28days")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class GoogleAnalyticsSyncError(RuntimeError):
    """Safe error whose text never includes credentials or provider bodies."""


def _numeric(value: object) -> int:
    try:
        return max(0, int(float(str(value or "0"))))
    except (TypeError, ValueError):
        return 0


def parse_ga4_report(payload: dict) -> dict[str, int]:
    names = [str(row.get("name") or "") for row in payload.get("metricHeaders", [])]
    rows = payload.get("rows") or []
    values = rows[0].get("metricValues", []) if rows else []
    by_name = {
        name: _numeric(values[index].get("value"))
        for index, name in enumerate(names)
        if index < len(values)
    }
    return {
        "active_users": by_name.get("activeUsers", 0),
        "sessions": by_name.get("sessions", 0),
        "page_views": by_name.get("screenPageViews", 0),
        "key_events": by_name.get("keyEvents", 0),
    }


def _metadata_access_token() -> str:
    request = UrlRequest(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise GoogleAnalyticsSyncError("GoogleMetadataAuthenticationError") from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise GoogleAnalyticsSyncError("GoogleMetadataAuthenticationError")
    return token


def _impersonated_access_token(service_account: str, source_token: str) -> str:
    url = (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{quote(service_account, safe='')}:generateAccessToken"
    )
    body = json.dumps(
        {
            "delegates": [],
            "scope": ["https://www.googleapis.com/auth/analytics.readonly"],
            "lifetime": "3600s",
        }
    ).encode("utf-8")
    request = UrlRequest(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {source_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise GoogleAnalyticsSyncError("GoogleServiceAccountImpersonationPermissionError") from exc
        raise GoogleAnalyticsSyncError("GoogleServiceAccountImpersonationError") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise GoogleAnalyticsSyncError("GoogleServiceAccountImpersonationError") from exc
    token = str(payload.get("accessToken") or "").strip()
    if not token:
        raise GoogleAnalyticsSyncError("GoogleServiceAccountImpersonationError")
    return token


def _analytics_access_token() -> str:
    source_token = _metadata_access_token()
    if GA4_SERVICE_ACCOUNT:
        return _impersonated_access_token(GA4_SERVICE_ACCOUNT, source_token)
    return source_token


def fetch_ga4_report(property_id: str) -> dict:
    if not str(property_id or "").isdigit():
        raise GoogleAnalyticsSyncError("GoogleAnalyticsPropertyIdError")
    body = json.dumps(
        {
            "dateRanges": [{"startDate": "28daysAgo", "endDate": "today"}],
            "metrics": [
                {"name": "activeUsers"},
                {"name": "sessions"},
                {"name": "screenPageViews"},
                {"name": "keyEvents"},
            ],
            "keepEmptyRows": True,
        }
    ).encode("utf-8")
    request = UrlRequest(
        GA4_RUN_REPORT_URL.format(property_id=property_id),
        data=body,
        headers={
            "Authorization": f"Bearer {_analytics_access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise GoogleAnalyticsSyncError("GoogleAnalyticsPermissionError") from exc
        raise GoogleAnalyticsSyncError("GoogleAnalyticsAPIError") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise GoogleAnalyticsSyncError("GoogleAnalyticsAPIError") from exc


def latest_ga4_snapshot(
    db: Session, property_id: Optional[str] = None
) -> Optional[GoogleAnalyticsSnapshot]:
    stmt = select(GoogleAnalyticsSnapshot)
    if property_id:
        stmt = stmt.where(GoogleAnalyticsSnapshot.property_id == property_id)
    return db.scalar(stmt.order_by(GoogleAnalyticsSnapshot.fetched_at.desc()).limit(1))


def sync_ga4_snapshot(
    db: Session,
    property_id: str,
    *,
    fetch_report: Callable[[str], dict] = fetch_ga4_report,
) -> GoogleAnalyticsSnapshot:
    property_id = str(property_id or "").strip()
    if not property_id.isdigit():
        raise GoogleAnalyticsSyncError("GoogleAnalyticsPropertyIdError")
    try:
        metrics = parse_ga4_report(fetch_report(property_id))
    except GoogleAnalyticsSyncError:
        raise
    except PermissionError as exc:
        raise GoogleAnalyticsSyncError("GoogleAnalyticsPermissionError") from exc
    except Exception as exc:
        raise GoogleAnalyticsSyncError("GoogleAnalyticsAPIError") from exc

    now = datetime.now(timezone.utc)
    row = db.scalar(
        select(GoogleAnalyticsSnapshot).where(
            GoogleAnalyticsSnapshot.property_id == property_id
        )
    )
    if row is None:
        row = GoogleAnalyticsSnapshot(property_id=property_id)
        db.add(row)
    row.active_users = metrics["active_users"]
    row.sessions = metrics["sessions"]
    row.page_views = metrics["page_views"]
    row.key_events = metrics["key_events"]
    row.period = "last28days"
    row.fetched_at = now
    db.commit()
    db.refresh(row)
    return row


def refresh_ga4_if_stale(
    db: Session,
    property_id: str,
    *,
    fetch_report: Callable[[str], dict] = fetch_ga4_report,
    max_age: timedelta = timedelta(minutes=15),
) -> GoogleAnalyticsSnapshot:
    row = latest_ga4_snapshot(db, property_id)
    if row is not None:
        fetched_at = row.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched_at <= max_age:
            return row
    return sync_ga4_snapshot(db, property_id, fetch_report=fetch_report)


def google_analytics_connection_state(
    db: Session, property_id: Optional[str] = None
) -> tuple[str, str]:
    property_id = str(GA4_PROPERTY_ID if property_id is None else property_id).strip()
    if not property_id:
        return "Needs Integration", "Google Analytics Property ID is missing"
    if not property_id.isdigit():
        return "Needs Integration", "Google Analytics Property ID is invalid"
    row = latest_ga4_snapshot(db, property_id)
    if row is None:
        return "Needs Integration", "Property configured; awaiting first successful GA4 read"
    return "Connected", f"GA4 read-only · last successful read {core.fmt_dt(row.fetched_at)}"
