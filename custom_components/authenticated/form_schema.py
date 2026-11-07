"""Config form schema using probatio, the validator shipped with Home Assistant 2026.11.

Core no longer installs voluptuous. Importing it crashes config and options
flows on that release. The tests construct this schema directly so they do not
depend on a stubbed validator.
"""

from __future__ import annotations

from numbers import Number

import probatio as vol

from .const import (
    CONF_ENRICH_PUBLIC_IPS,
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_HISTORY_MAX_EVENTS,
    CONF_HISTORY_RETENTION_DAYS,
    CONF_NOTIFY,
    CONF_NOTIFY_EXCLUDE_ASN,
    CONF_NOTIFY_EXCLUDE_HOSTNAMES,
    CONF_NOTIFY_ON,
    CONF_NOTIFY_SERVICES,
    CONF_PROVIDER,
    CONF_RESOLVE_HOSTNAMES,
    CONF_STORE_USERNAMES,
    MAX_MAX_EVENTS,
    MAX_RETENTION_DAYS,
    MIN_MAX_EVENTS,
    MIN_RETENTION_DAYS,
    NOTIFY_ON_CHOICES,
    PROVIDERS,
)


def boolean(value: object) -> bool:
    """Accept the same boolean spellings Home Assistant's config validator accepts."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.lower().strip()
        if text in ("1", "true", "yes", "on", "enable"):
            return True
        if text in ("0", "false", "no", "off", "disable"):
            return False
    elif isinstance(value, Number) and not isinstance(value, bool):
        return value != 0
    raise vol.Invalid("invalid boolean value")


def build_form_schema(defaults: dict) -> vol.Schema:
    """Schema shared by the user step and the options step."""
    return vol.Schema(
        {
            vol.Optional(CONF_PROVIDER, default=defaults[CONF_PROVIDER]): vol.In(list(PROVIDERS)),
            vol.Optional(CONF_ENRICH_PUBLIC_IPS, default=defaults[CONF_ENRICH_PUBLIC_IPS]): boolean,
            vol.Optional(CONF_NOTIFY, default=defaults[CONF_NOTIFY]): boolean,
            vol.Optional(CONF_NOTIFY_ON, default=defaults[CONF_NOTIFY_ON]): vol.In(
                NOTIFY_ON_CHOICES
            ),
            vol.Optional(CONF_NOTIFY_SERVICES, default=defaults[CONF_NOTIFY_SERVICES]): str,
            vol.Optional(CONF_EXCLUDE, default=defaults[CONF_EXCLUDE]): str,
            vol.Optional(CONF_EXCLUDE_CLIENTS, default=defaults[CONF_EXCLUDE_CLIENTS]): str,
            vol.Optional(
                CONF_NOTIFY_EXCLUDE_ASN, default=defaults[CONF_NOTIFY_EXCLUDE_ASN]
            ): str,
            vol.Optional(
                CONF_NOTIFY_EXCLUDE_HOSTNAMES,
                default=defaults[CONF_NOTIFY_EXCLUDE_HOSTNAMES],
            ): str,
            vol.Optional(
                CONF_HISTORY_RETENTION_DAYS,
                default=defaults[CONF_HISTORY_RETENTION_DAYS],
            ): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_RETENTION_DAYS, max=MAX_RETENTION_DAYS)
            ),
            vol.Optional(
                CONF_HISTORY_MAX_EVENTS, default=defaults[CONF_HISTORY_MAX_EVENTS]
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MAX_EVENTS, max=MAX_MAX_EVENTS)),
            vol.Optional(CONF_STORE_USERNAMES, default=defaults[CONF_STORE_USERNAMES]): boolean,
            vol.Optional(
                CONF_RESOLVE_HOSTNAMES, default=defaults[CONF_RESOLVE_HOSTNAMES]
            ): boolean,
        }
    )
