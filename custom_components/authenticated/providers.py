"""Async IP enrichment. Non-public addresses are not requested."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging

import aiohttp

from .const import (
    GEO_RESPONSE_BYTES,
    PROVIDER_IPAPI,
    PROVIDER_IPINFO,
    USER_AGENT,
)
from .history import geo_from_mapping, geo_is_populated
from .ip_util import canonical_ip, enrichment_allowed

_LOGGER = logging.getLogger(__name__)

_URLS = {
    PROVIDER_IPAPI: "https://ipapi.co/{ip}/json",
    PROVIDER_IPINFO: "https://ipinfo.io/{ip}/json",
}

PROVIDERS: dict[str, type] = {}


def register_provider(classname):
    """Register a provider class."""
    PROVIDERS[classname.name] = classname
    return classname


@dataclass(frozen=True)
class GeoResult:
    """Normalized enrichment outcome. ``fields`` never includes the raw payload."""

    status: str
    fields: dict
    retry_after: float | None = None


def build_url(provider: str, ip: str) -> str:
    """Build a provider URL for an address that is allowed to leave the host."""
    if provider not in _URLS:
        raise ValueError("unknown_provider")
    if not enrichment_allowed(ip):
        raise ValueError("non_public")
    canonical = canonical_ip(ip)
    if canonical is None:
        raise ValueError("non_public")
    return _URLS[provider].format(ip=canonical)


def _retry_after(headers: dict | None) -> float | None:
    if not headers:
        return None
    raw = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if 1 <= seconds <= 6 * 60 * 60:
        return float(seconds)
    return None


def _reason(data: dict) -> str | None:
    reason = data.get("reason")
    if isinstance(reason, str):
        return reason
    error = data.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        title = error.get("title") or error.get("message")
        if isinstance(title, str):
            return title
    status = data.get("status")
    if isinstance(status, str):
        return status
    return None


def _is_rate_limited(status: int, data: object) -> bool:
    if status == 429:
        return True
    if not isinstance(data, dict):
        return False
    reason = _reason(data)
    return bool(reason and "rate" in reason.lower())


def _split_org(org: object) -> tuple[str | None, str | None]:
    if not isinstance(org, str) or not org.strip():
        return None, None
    parts = org.strip().split(" ", 1)
    asn = parts[0]
    name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return asn, name


def _languages(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if texts:
            return ",".join(texts)
    return None


def _ipapi_fields(data: dict) -> dict:
    code = data.get("country_code") or data.get("country")
    country = data.get("country_name") or code
    return geo_from_mapping(
        {
            "country": country,
            "country_code": code,
            "region": data.get("region"),
            "city": data.get("city"),
            "asn": data.get("asn"),
            "org": data.get("org"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": data.get("timezone"),
            "currency": data.get("currency"),
            "languages": _languages(data.get("languages")),
            "postal": data.get("postal"),
        }
    )


def _ipinfo_fields(data: dict) -> dict:
    asn, org = _split_org(data.get("org"))
    latitude = None
    longitude = None
    loc = data.get("loc")
    if isinstance(loc, str) and "," in loc:
        left, right = loc.split(",", 1)
        latitude, longitude = left, right
    code = data.get("country")
    return geo_from_mapping(
        {
            "country": data.get("country_name") or code,
            "country_code": code,
            "region": data.get("region"),
            "city": data.get("city"),
            "asn": asn,
            "org": org,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": data.get("timezone"),
            "currency": data.get("currency"),
            "languages": _languages(data.get("languages")),
            "postal": data.get("postal"),
        }
    )


def interpret_response(
    provider: str,
    status: int | None,
    body: object,
    headers: dict | None,
    failure: str | None,
) -> GeoResult:
    """Map a provider response to a retryable status. The body is not retained."""
    retry_after = _retry_after(headers)
    if failure is not None or status is None:
        return GeoResult("error", {}, retry_after)
    if _is_rate_limited(status, body):
        return GeoResult("rate_limited", {}, retry_after)
    if status != 200:
        return GeoResult("error", {}, retry_after)
    if not isinstance(body, dict):
        return GeoResult("error", {}, retry_after)
    if body.get("reserved") is True or body.get("bogon") is True:
        return GeoResult("skipped", {}, None)
    reason = _reason(body)
    if body.get("error") or (isinstance(reason, str) and reason.lower() in {"error", "fail"}):
        return GeoResult("error", {}, retry_after)
    if body.get("status") in {"error", "fail"}:
        return GeoResult("error", {}, retry_after)
    if provider == PROVIDER_IPINFO:
        fields = _ipinfo_fields(body)
    else:
        fields = _ipapi_fields(body)
    if geo_is_populated(fields):
        return GeoResult("complete", fields, None)
    return GeoResult("incomplete", {}, None)


async def read_http(session, url: str) -> tuple[int | None, object, dict, str | None]:
    """Perform one GET. Redirects are not followed. Errors do not include the URL."""
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_read=8)
    try:
        async with session.get(
            url,
            allow_redirects=False,
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status in {301, 302, 303, 307, 308}:
                return response.status, None, {}, "redirect"
            raw = await response.content.read(GEO_RESPONSE_BYTES + 1)
            response_headers = {}
            retry = response.headers.get("Retry-After") if response.headers else None
            if retry is not None:
                response_headers["Retry-After"] = retry
            status = response.status
    except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError):
        return None, None, {}, "transport"
    if len(raw) > GEO_RESPONSE_BYTES:
        return status, None, response_headers, "too_large"
    try:
        text = raw.decode("utf-8")
        body = json.loads(text) if text.strip() else None
    except (UnicodeError, json.JSONDecodeError):
        return status, None, response_headers, "invalid_json"
    return status, body, response_headers, None


async def async_lookup_ip(session, provider: str, ip: str) -> GeoResult:
    """Look up one public address. Any failure becomes a result, not a raise."""
    if not enrichment_allowed(ip):
        return GeoResult("skipped", {})
    try:
        url = build_url(provider, ip)
    except ValueError:
        return GeoResult("error", {})
    status, body, headers, failure = await read_http(session, url)
    if failure == "transport":
        _LOGGER.warning("Geo lookup failed for provider %s (transport)", provider)
    elif failure:
        _LOGGER.warning("Geo lookup failed for provider %s (%s)", provider, failure)
    elif status != 200:
        _LOGGER.warning("Geo lookup failed for provider %s (http_%s)", provider, status)
    return interpret_response(provider, status, body, headers, failure)


def create_session() -> aiohttp.ClientSession:
    """Return a session that does not inherit environment proxy settings."""
    return aiohttp.ClientSession(
        trust_env=False,
        timeout=aiohttp.ClientTimeout(total=10, connect=5, sock_read=8),
        headers={"User-Agent": USER_AGENT},
    )


class GeoProvider:
    """Provider base kept for the org parser and the config-flow registry."""

    name = "base"
    url = None

    def __init__(self, ipaddr: str) -> None:
        self.ipaddr = ipaddr
        self.result: dict = {}

    async def async_update_geo_info(self, session=None) -> GeoResult:
        """Fetch geo information. A temporary session is closed when we create it."""
        if not enrichment_allowed(self.ipaddr):
            self.result = {}
            return GeoResult("skipped", {})
        close_session = False
        if session is None:
            session = create_session()
            close_session = True
        try:
            outcome = await async_lookup_ip(session, self.name, self.ipaddr)
        finally:
            if close_session:
                await session.close()
        self.result = dict(outcome.fields)
        return outcome

    @property
    def country(self):
        return self.result.get("country_name") or self.result.get("country")

    @property
    def region(self):
        return self.result.get("region")

    @property
    def city(self):
        return self.result.get("city")

    @property
    def asn(self):
        return self.result.get("asn")

    @property
    def org(self):
        return self.result.get("org")

    @property
    def latitude(self):
        return self.result.get("latitude")

    @property
    def longitude(self):
        return self.result.get("longitude")

    @property
    def timezone(self):
        return self.result.get("timezone")

    @property
    def currency(self):
        return self.result.get("currency")

    @property
    def languages(self):
        return self.result.get("languages")

    @property
    def postal(self):
        return self.result.get("postal")

    @property
    def country_code(self):
        return self.result.get("country_code")


@register_provider
class IPApi(GeoProvider):
    """ipapi.co provider."""

    url = _URLS[PROVIDER_IPAPI]
    name = PROVIDER_IPAPI


@register_provider
class IPInfo(GeoProvider):
    """ipinfo.io provider."""

    url = _URLS[PROVIDER_IPINFO]
    name = PROVIDER_IPINFO

    @property
    def asn(self):
        org = self.result.get("org")
        if not isinstance(org, str) or not org:
            return self.result.get("asn")
        return org.split(" ", 1)[0]

    @property
    def org(self):
        org = self.result.get("org")
        if not isinstance(org, str) or not org:
            return None
        parts = org.split(" ", 1)
        return parts[1] if len(parts) > 1 and parts[1] else None
