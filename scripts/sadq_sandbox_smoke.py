#!/usr/bin/env python3
"""Read-only Sadq sandbox smoke test for Pakgat.

Checks vendor-documented integration authentication, performs an authenticated
GET of Sadq webhook configuration, and probes Pakgat's public Sadq callback
without credentials. It never creates an envelope, invitation, or Nafath
request, and it never prints access tokens or submitted secrets.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://sandbox-api.sadq-sa.com"
DEFAULT_CALLBACK_URL = "https://voucher.pakgat.com/integrations/sadq/webhook"


class SmokeError(RuntimeError):
    """Safe diagnostic error whose message must not contain provider secrets."""


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    client_id: str
    client_secret: str
    username: str
    password: str
    account_id: str
    account_secret: str
    callback_url: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class SmokeResult:
    api_ok: bool
    webhook_count: int
    callback_registered: bool
    callback_probe_status: int
    ready_for_e2e: bool


Transport = Callable[
    [str, str, dict[str, str] | None, bytes | None, int], HttpResponse
]


def _safe_url(value: str, name: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise SmokeError(f"{name} must be a valid https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SmokeError(f"{name} must not include credentials, query, or fragment")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _required(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise SmokeError(f"Missing required value: {label}")
    return clean


def default_transport(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 20,
) -> HttpResponse:
    request = Request(
        url,
        data=body,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()))
            return HttpResponse(status=status, body=response.read())
    except HTTPError as exc:
        try:
            body_bytes = exc.read()
        except Exception:
            body_bytes = b""
        return HttpResponse(status=int(exc.code), body=body_bytes)
    except URLError as exc:
        reason = getattr(exc, "reason", None)
        reason_name = type(reason).__name__ if reason is not None else "URLError"
        raise SmokeError(
            f"Network/DNS/TLS failure while contacting remote endpoint ({reason_name})"
        ) from None
    except TimeoutError:
        raise SmokeError("Network timeout while contacting remote endpoint") from None
    except OSError as exc:
        raise SmokeError(
            f"Network failure while contacting remote endpoint ({type(exc).__name__})"
        ) from None


def _json_object(response: HttpResponse, stage: str) -> dict:
    if not (200 <= response.status < 300):
        raise SmokeError(f"{stage} returned HTTP {response.status}")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except Exception:
        raise SmokeError(f"{stage} returned invalid JSON") from None
    if not isinstance(value, dict):
        raise SmokeError(f"{stage} returned an unexpected JSON shape")
    return value


def _print(out: TextIO, marker: str) -> None:
    print(marker, file=out, flush=True)


def _normalized_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, "", ""))


def _extract_webhooks(payload: dict) -> list[dict]:
    data = payload.get("data", [])
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise SmokeError("Sadq webhook list returned an unexpected data shape")


def run_read_only(
    config: SmokeConfig,
    *,
    transport: Transport = default_transport,
    out: TextIO = sys.stdout,
    timeout: int = 20,
) -> SmokeResult:
    """Run non-mutating integration checks and return a structured result."""
    base_url = _safe_url(config.base_url, "Sadq base URL")
    callback_url = _safe_url(config.callback_url, "Pakgat callback URL")
    client_id = _required(config.client_id, "Sadq Basic Client ID")
    client_secret = _required(config.client_secret, "Sadq Basic Client Secret")
    username = _required(config.username, "Sadq integration username")
    password = _required(config.password, "Sadq integration password")
    account_id = _required(config.account_id, "Sadq Account ID")
    account_secret = _required(config.account_secret, "Sadq Account Secret")

    basic = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
    auth_body = urlencode(
        {
            "grant_type": "integration",
            "password": password,
            "username": username,
            "accountId": account_id,
            "accountSecret": account_secret,
        }
    ).encode("utf-8")
    auth_response = transport(
        "POST",
        f"{base_url}/Authentication/Authority/Token",
        {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Pakgat-Sadq-Smoke/1.0",
        },
        auth_body,
        timeout,
    )
    _print(out, "SADQ_NETWORK_OK")
    auth_payload = _json_object(auth_response, "Sadq authentication")
    access_token = str(auth_payload.get("access_token") or "").strip()
    if not access_token:
        raise SmokeError(
            "Sadq authentication succeeded at HTTP level but no access_token was returned"
        )
    _print(out, "SADQ_AUTH_OK")

    webhook_response = transport(
        "GET",
        f"{base_url}/api/v1/webhooks",
        {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Pakgat-Sadq-Smoke/1.0",
        },
        None,
        timeout,
    )
    webhook_payload = _json_object(webhook_response, "Sadq webhook list")
    error_code = webhook_payload.get("errorCode")
    if error_code not in (None, 0, "0"):
        raise SmokeError(
            f"Sadq webhook list returned provider errorCode={error_code}"
        )
    webhooks = _extract_webhooks(webhook_payload)
    _print(out, "SADQ_BEARER_API_OK")
    _print(out, f"SADQ_WEBHOOK_LIST_OK count={len(webhooks)}")

    expected = _normalized_url(callback_url)
    callback_registered = any(
        _normalized_url(item.get("webhookUrl", "")) == expected
        for item in webhooks
        if item.get("webhookUrl")
    )
    if callback_registered:
        _print(out, "SADQ_CALLBACK_REGISTERED")
    else:
        _print(out, "SADQ_CALLBACK_NOT_REGISTERED")

    callback_response = transport(
        "POST",
        callback_url,
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Pakgat-Sadq-Smoke/1.0",
        },
        b"{}",
        timeout,
    )
    if callback_response.status == 403:
        _print(out, "PAKGAT_CALLBACK_REACHABLE_AND_PROTECTED")
        callback_protected = True
    elif callback_response.status == 503:
        _print(out, "PAKGAT_CALLBACK_REACHABLE_BUT_TOKEN_NOT_CONFIGURED")
        callback_protected = False
    elif callback_response.status == 200:
        _print(out, "PAKGAT_CALLBACK_UNEXPECTEDLY_ACCEPTED_UNAUTHENTICATED_REQUEST")
        callback_protected = False
    else:
        _print(out, f"PAKGAT_CALLBACK_PROBE_HTTP_{callback_response.status}")
        callback_protected = False

    _print(out, "SADQ_READ_ONLY_API_OK")
    ready = bool(callback_registered and callback_protected)
    if ready:
        _print(out, "SADQ_INTEGRATION_READY_FOR_E2E")
    else:
        _print(out, "SADQ_INTEGRATION_NOT_READY_FOR_E2E")

    return SmokeResult(
        api_ok=True,
        webhook_count=len(webhooks),
        callback_registered=callback_registered,
        callback_probe_status=callback_response.status,
        ready_for_e2e=ready,
    )


def _plain_prompt(env_name: str, label: str, default: str = "") -> str:
    existing = os.getenv(env_name, "").strip()
    if existing:
        return existing
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _secret_prompt(env_name: str, label: str) -> str:
    existing = os.getenv(env_name, "").strip()
    if existing:
        return existing
    return getpass.getpass(f"{label}: ").strip()


def interactive_config() -> SmokeConfig:
    print(
        "Sadq sandbox read-only smoke test. "
        "Secrets are hidden and are not persisted."
    )
    return SmokeConfig(
        base_url=_plain_prompt(
            "SADQ_API_BASE_URL", "Sadq sandbox URL", DEFAULT_BASE_URL
        ),
        client_id=_plain_prompt("SADQ_CLIENT_ID", "Sadq Basic Client ID"),
        client_secret=_secret_prompt(
            "SADQ_CLIENT_SECRET", "Sadq Basic Client Secret"
        ),
        username=_plain_prompt("SADQ_USERNAME", "Sadq integration username"),
        password=_secret_prompt("SADQ_PASSWORD", "Sadq integration password"),
        account_id=_plain_prompt("SADQ_ACCOUNT_ID", "Sadq Account ID"),
        account_secret=_secret_prompt(
            "SADQ_ACCOUNT_SECRET", "Sadq Account Secret"
        ),
        callback_url=_plain_prompt(
            "SADQ_CALLBACK_URL",
            "Pakgat public callback URL",
            DEFAULT_CALLBACK_URL,
        ),
    )


def main() -> int:
    try:
        result = run_read_only(interactive_config())
    except (KeyboardInterrupt, EOFError):
        print("\nSMOKE_CANCELLED", file=sys.stderr)
        return 130
    except SmokeError as exc:
        print(f"SADQ_SMOKE_FAILED: {exc}", file=sys.stderr)
        return 1

    return 0 if result.api_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
