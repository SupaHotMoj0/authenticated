"""Validation for integration options.

Form input is strict so the UI can show an error. Stored config is lenient so a
hand-edited value cannot stop observation; unsafe values fall back to defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_network
import re

from .const import (
    CONF_ENRICH_PUBLIC_IPS,
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_HISTORY_MAX_EVENTS,
    CONF_HISTORY_RETENTION_DAYS,
    CONF_LOG_LOCATION,
    CONF_NOTIFY,
    CONF_NOTIFY_EXCLUDE_ASN,
    CONF_NOTIFY_EXCLUDE_HOSTNAMES,
    CONF_NOTIFY_ON,
    CONF_NOTIFY_SERVICES,
    CONF_PROVIDER,
    CONF_RESOLVE_HOSTNAMES,
    CONF_STORE_USERNAMES,
    DEFAULT_MAX_EVENTS,
    DEFAULT_RETENTION_DAYS,
    LIST_LIMIT,
    MAX_MAX_EVENTS,
    MAX_RETENTION_DAYS,
    MIN_MAX_EVENTS,
    MIN_RETENTION_DAYS,
    NOTIFY_ON_CHOICES,
    NOTIFY_ON_NEW_IP,
    NOTIFY_SERVICE_LIMIT,
    OUTFILE,
    PROVIDER_IPAPI,
    PROVIDERS,
    TEXT_LIMIT,
)
from .ip_util import safe_config_relative

_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")


class SettingsError(ValueError):
    """A config value failed validation."""

    def __init__(self, key: str, field: str = "base") -> None:
        super().__init__(key)
        self.key = key
        self.field = field


@dataclass(frozen=True)
class Settings:
    """Effective runtime settings."""

    provider: str = PROVIDER_IPAPI
    notify: bool = True
    notify_services: tuple[str, ...] = ()
    notify_on: str = NOTIFY_ON_NEW_IP
    exclude: tuple[str, ...] = ()
    exclude_clients: tuple[str, ...] = ()
    notify_exclude_asn: tuple[str, ...] = ()
    notify_exclude_hostnames: tuple[str, ...] = ()
    retention_days: int = DEFAULT_RETENTION_DAYS
    max_events: int = DEFAULT_MAX_EVENTS
    store_usernames: bool = False
    enrich_public_ips: bool = True
    resolve_hostnames: bool = False
    history_relative: str = OUTFILE

    def as_dict(self) -> dict:
        """Return the JSON/YAML fragment stored in a config entry."""
        return {
            CONF_PROVIDER: self.provider,
            CONF_NOTIFY: self.notify,
            CONF_NOTIFY_SERVICES: list(self.notify_services),
            CONF_NOTIFY_ON: self.notify_on,
            CONF_EXCLUDE: list(self.exclude),
            CONF_EXCLUDE_CLIENTS: list(self.exclude_clients),
            CONF_NOTIFY_EXCLUDE_ASN: list(self.notify_exclude_asn),
            CONF_NOTIFY_EXCLUDE_HOSTNAMES: list(self.notify_exclude_hostnames),
            CONF_HISTORY_RETENTION_DAYS: self.retention_days,
            CONF_HISTORY_MAX_EVENTS: self.max_events,
            CONF_STORE_USERNAMES: self.store_usernames,
            CONF_ENRICH_PUBLIC_IPS: self.enrich_public_ips,
            CONF_RESOLVE_HOSTNAMES: self.resolve_hostnames,
        }


def _csv(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                raise SettingsError("invalid_options")
    else:
        raise SettingsError("invalid_options")
    cleaned = []
    for part in parts:
        text = part.strip()
        if text:
            cleaned.append(text)
    return cleaned


def normalize_notify_service(value: str) -> str:
    """Return the notify service name without a domain prefix."""
    text = value.strip().lower()
    if text.startswith("notify."):
        text = text[len("notify.") :]
    if not _SERVICE_NAME.fullmatch(text):
        raise SettingsError("invalid_notify_service", CONF_NOTIFY_SERVICES)
    return text


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _bounded_int(value: object, default: int, low: int, high: int, *, strict: bool) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as err:
        if strict:
            raise SettingsError("invalid_options") from err
        return default
    if number < low or number > high:
        if strict:
            raise SettingsError("invalid_options")
        return default
    return number


def _services(value: object, *, strict: bool) -> tuple[str, ...]:
    try:
        items = _csv(value)
    except SettingsError:
        if strict:
            raise
        return ()
    if len(items) > NOTIFY_SERVICE_LIMIT:
        if strict:
            raise SettingsError("invalid_notify_service", CONF_NOTIFY_SERVICES)
        items = items[:NOTIFY_SERVICE_LIMIT]
    normalized: list[str] = []
    for item in items:
        try:
            service = normalize_notify_service(item)
        except SettingsError:
            if strict:
                raise
            continue
        if service not in normalized:
            normalized.append(service)
    return tuple(normalized)


def _networks(value: object, *, strict: bool) -> tuple[str, ...]:
    try:
        items = _csv(value)
    except SettingsError:
        if strict:
            raise
        return ()
    if len(items) > LIST_LIMIT:
        if strict:
            raise SettingsError("invalid_network", CONF_EXCLUDE)
        items = items[:LIST_LIMIT]
    networks: list[str] = []
    for item in items:
        try:
            network = ip_network(item, strict=False)
        except ValueError as err:
            if strict:
                raise SettingsError("invalid_network", CONF_EXCLUDE) from err
            continue
        text = str(network)
        if text not in networks:
            networks.append(text)
    return tuple(networks)


def _texts(value: object, *, strict: bool, field: str) -> tuple[str, ...]:
    try:
        items = _csv(value)
    except SettingsError:
        if strict:
            raise
        return ()
    if len(items) > LIST_LIMIT or any(len(item) > TEXT_LIMIT for item in items):
        if strict:
            raise SettingsError("invalid_options", field)
        items = [item[:TEXT_LIMIT] for item in items[:LIST_LIMIT]]
    unique: list[str] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def settings_from_mapping(mapping: object, *, strict: bool = False) -> Settings:
    """Build settings from a config entry, options dict, or YAML block."""
    data = mapping if isinstance(mapping, dict) else {}
    provider = data.get(CONF_PROVIDER, PROVIDER_IPAPI)
    if not isinstance(provider, str) or provider not in PROVIDERS:
        if strict:
            raise SettingsError("invalid_provider", CONF_PROVIDER)
        provider = PROVIDER_IPAPI
    notify_on = data.get(CONF_NOTIFY_ON, NOTIFY_ON_NEW_IP)
    if notify_on not in NOTIFY_ON_CHOICES:
        if strict:
            raise SettingsError("invalid_options", CONF_NOTIFY_ON)
        notify_on = NOTIFY_ON_NEW_IP
    history_relative = OUTFILE
    if CONF_LOG_LOCATION in data and data.get(CONF_LOG_LOCATION) not in ("", None):
        safe = safe_config_relative(data.get(CONF_LOG_LOCATION))
        if safe is None:
            if strict:
                raise SettingsError("invalid_options", CONF_LOG_LOCATION)
        else:
            history_relative = safe
    return Settings(
        provider=provider,
        notify=_bool(data.get(CONF_NOTIFY), True),
        notify_services=_services(data.get(CONF_NOTIFY_SERVICES), strict=strict),
        notify_on=notify_on,
        exclude=_networks(data.get(CONF_EXCLUDE), strict=strict),
        exclude_clients=_texts(
            data.get(CONF_EXCLUDE_CLIENTS), strict=strict, field=CONF_EXCLUDE_CLIENTS
        ),
        notify_exclude_asn=_texts(
            data.get(CONF_NOTIFY_EXCLUDE_ASN),
            strict=strict,
            field=CONF_NOTIFY_EXCLUDE_ASN,
        ),
        notify_exclude_hostnames=_texts(
            data.get(CONF_NOTIFY_EXCLUDE_HOSTNAMES),
            strict=strict,
            field=CONF_NOTIFY_EXCLUDE_HOSTNAMES,
        ),
        retention_days=_bounded_int(
            data.get(CONF_HISTORY_RETENTION_DAYS),
            DEFAULT_RETENTION_DAYS,
            MIN_RETENTION_DAYS,
            MAX_RETENTION_DAYS,
            strict=strict,
        ),
        max_events=_bounded_int(
            data.get(CONF_HISTORY_MAX_EVENTS),
            DEFAULT_MAX_EVENTS,
            MIN_MAX_EVENTS,
            MAX_MAX_EVENTS,
            strict=strict,
        ),
        store_usernames=_bool(data.get(CONF_STORE_USERNAMES), False),
        enrich_public_ips=_bool(data.get(CONF_ENRICH_PUBLIC_IPS), True),
        resolve_hostnames=_bool(data.get(CONF_RESOLVE_HOSTNAMES), False),
        history_relative=history_relative,
    )


def storage_from_form(user_input: dict) -> dict:
    """Validate a form submission and return the stored options dict."""
    return settings_from_mapping(user_input, strict=True).as_dict()


def merged_mapping(data: object, options: object) -> dict:
    """Options override the original config-entry data."""
    merged: dict = {}
    if isinstance(data, dict):
        merged.update(data)
    if isinstance(options, dict):
        merged.update(options)
    return merged
