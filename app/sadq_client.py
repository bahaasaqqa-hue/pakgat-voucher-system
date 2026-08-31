"""Authenticated Sadq API client for Pakgat merchant onboarding.

This module owns dynamic Integration-token retrieval and webhook registration.
It does not create envelopes or Nafath invitations; those are separate stages.
Secrets are read from environment variables and are never logged.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://sandbox-api.sadq-sa.com"
DEFAULT_WEBHOOK_URL = "https://voucher.pakgat.com/integrations/sadq/webhook"
TOKEN_REFRESH_SKEW_SECONDS = 120


class SadqError(RuntimeError):
    """Safe provider-facing error that must never include submitted secrets."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


Transport = Callable[
    [str, str, dict[str, str] | None, bytes | None, int], HttpResponse
]


def _required(value: str, label: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise SadqError(f"Missing required Sadq configuration: {label}")
    return clean


def _https_url(value: str, label: str) -> str:
    raw = _required(value, label).rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise SadqError(f"Invalid Sadq configuration URL: {label}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SadqError(f"Invalid Sadq configuration URL: {label}")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class SadqConfig:
    base_url: str
    client_id: str
    client_secret: str
    username: str
    password: str
    account_id: str
    account_secret: str
    webhook_url: str
    webhook_token: str

    @classmethod
    def from_env(cls) -> "SadqConfig":
        return cls(
            base_url=_https_url(
                os.getenv("SADQ_API_BASE_URL", DEFAULT_BASE_URL),
                "SADQ_API_BASE_URL",
            ),
            client_id=_required(os.getenv("SADQ_CLIENT_ID", ""), "SADQ_CLIENT_ID"),
            client_secret=_required(
                os.getenv("SADQ_CLIENT_SECRET", ""), "SADQ_CLIENT_SECRET"
            ),
            username=_required(os.getenv("SADQ_USERNAME", ""), "SADQ_USERNAME"),
            password=_required(os.getenv("SADQ_PASSWORD", ""), "SADQ_PASSWORD"),
            account_id=_required(
                os.getenv("SADQ_ACCOUNT_ID", ""), "SADQ_ACCOUNT_ID"
            ),
            account_secret=_required(
                os.getenv("SADQ_ACCOUNT_SECRET", ""), "SADQ_ACCOUNT_SECRET"
            ),
            webhook_url=_https_url(
                os.getenv("SADQ_WEBHOOK_URL", DEFAULT_WEBHOOK_URL),
                "SADQ_WEBHOOK_URL",
            ),
            webhook_token=_required(
                os.getenv("SADQ_WEBHOOK_TOKEN", ""), "SADQ_WEBHOOK_TOKEN"
            ),
        )


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
            payload = exc.read()
        except Exception:
            payload = b""
        return HttpResponse(status=int(exc.code), body=payload)
    except (URLError, TimeoutError, OSError) as exc:
        raise SadqError(
            f"Sadq network request failed ({type(exc).__name__})"
        ) from None


def _json_object(response: HttpResponse, stage: str) -> dict:
    if not 200 <= response.status < 300:
        raise SadqError(f"{stage} returned HTTP {response.status}")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except Exception:
        raise SadqError(f"{stage} returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise SadqError(f"{stage} returned an unexpected JSON shape")
    error_code = payload.get("errorCode")
    if error_code not in (None, 0, "0"):
        raise SadqError(f"{stage} returned provider errorCode={error_code}")
    return payload


def _normalized_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            "",
        )
    )


class SadqClient:
    def __init__(
        self,
        config: SadqConfig,
        *,
        transport: Transport = default_transport,
        clock: Callable[[], float] = time.time,
        timeout: int = 20,
    ):
        self.config = config
        self.transport = transport
        self.clock = clock
        self.timeout = timeout
        self._access_token = ""
        self._access_token_expires_at = 0.0

    def _token_is_fresh(self) -> bool:
        return bool(
            self._access_token
            and self.clock()
            < self._access_token_expires_at - TOKEN_REFRESH_SKEW_SECONDS
        )

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._token_is_fresh():
            return self._access_token

        basic_value = base64.b64encode(
            f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        ).decode("ascii")
        body = urlencode(
            {
                "grant_type": "integration",
                "username": self.config.username,
                "password": self.config.password,
                "accountId": self.config.account_id,
                "accountSecret": self.config.account_secret,
            }
        ).encode("utf-8")
        response = self.transport(
            "POST",
            f"{self.config.base_url.rstrip('/')}/Authentication/Authority/Token",
            {
                "Authorization": f"Basic {basic_value}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "Pakgat-Sadq/1.0",
            },
            body,
            self.timeout,
        )
        payload = _json_object(response, "Sadq authentication")
        token = str(payload.get("access_token") or "").strip()
        if not token:
            safe_error = str(payload.get("error") or "").strip()
            if safe_error:
                raise SadqError(f"Sadq authentication failed: {safe_error}")
            raise SadqError("Sadq authentication returned no access token")
        try:
            expires_in = max(1, int(payload.get("expires_in") or 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self._access_token = token
        self._access_token_expires_at = self.clock() + expires_in
        return token

    def _authorized_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        retry_auth: bool = True,
    ) -> dict:
        token = self.get_access_token()
        body = None
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Pakgat-Sadq/1.0",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        response = self.transport(
            method,
            f"{self.config.base_url.rstrip('/')}{path}",
            headers,
            body,
            self.timeout,
        )
        if response.status in (401, 403) and retry_auth:
            self._access_token = ""
            self._access_token_expires_at = 0.0
            self.get_access_token(force_refresh=True)
            return self._authorized_json(
                method,
                path,
                payload=payload,
                retry_auth=False,
            )
        return _json_object(response, f"Sadq {method.upper()} {path}")

    def list_webhooks(self) -> list[dict]:
        payload = self._authorized_json("GET", "/api/v1/webhooks")
        data = payload.get("data", [])
        if data is None:
            return []
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        raise SadqError("Sadq webhook list returned an unexpected data shape")

    def ensure_webhook(self) -> dict:
        expected_url = _normalized_url(self.config.webhook_url)
        for item in self.list_webhooks():
            if _normalized_url(item.get("webhookUrl", "")) == expected_url:
                return item

        payload = self._authorized_json(
            "POST",
            "/api/v1/webhooks",
            payload={
                "webhookUrl": self.config.webhook_url,
                "isDefault": True,
                "HeaderToken": f"Bearer {self.config.webhook_token}",
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SadqError("Sadq webhook creation returned an unexpected data shape")
        return data


_default_client: SadqClient | None = None


def get_default_client(*, reset: bool = False) -> SadqClient:
    global _default_client
    if reset or _default_client is None:
        _default_client = SadqClient(SadqConfig.from_env())
    return _default_client


def get_access_token() -> str:
    return get_default_client().get_access_token()


def ensure_webhook() -> dict:
    return get_default_client().ensure_webhook()
