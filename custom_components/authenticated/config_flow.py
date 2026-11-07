"""Config and options flow for Authenticated."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
import homeassistant.helpers.config_validation as cv

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
    DOMAIN,
    MAX_MAX_EVENTS,
    MAX_RETENTION_DAYS,
    MIN_MAX_EVENTS,
    MIN_RETENTION_DAYS,
    NOTIFY_ON_CHOICES,
)
from .providers import PROVIDERS
from .settings import SettingsError, merged_mapping, settings_from_mapping, storage_from_form

_LIST_FIELDS = (
    CONF_NOTIFY_SERVICES,
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_NOTIFY_EXCLUDE_ASN,
    CONF_NOTIFY_EXCLUDE_HOSTNAMES,
)


def _form_defaults(mapping: dict) -> dict:
    settings = settings_from_mapping(mapping)
    data = settings.as_dict()
    for field in _LIST_FIELDS:
        data[field] = ", ".join(data[field])
    return data


def _schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_PROVIDER, default=defaults[CONF_PROVIDER]): vol.In(
                sorted(PROVIDERS)
            ),
            vol.Optional(CONF_ENRICH_PUBLIC_IPS, default=defaults[CONF_ENRICH_PUBLIC_IPS]): cv.boolean,
            vol.Optional(CONF_NOTIFY, default=defaults[CONF_NOTIFY]): cv.boolean,
            vol.Optional(CONF_NOTIFY_ON, default=defaults[CONF_NOTIFY_ON]): vol.In(
                NOTIFY_ON_CHOICES
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICES, default=defaults[CONF_NOTIFY_SERVICES]
            ): cv.string,
            vol.Optional(CONF_EXCLUDE, default=defaults[CONF_EXCLUDE]): cv.string,
            vol.Optional(CONF_EXCLUDE_CLIENTS, default=defaults[CONF_EXCLUDE_CLIENTS]): cv.string,
            vol.Optional(
                CONF_NOTIFY_EXCLUDE_ASN, default=defaults[CONF_NOTIFY_EXCLUDE_ASN]
            ): cv.string,
            vol.Optional(
                CONF_NOTIFY_EXCLUDE_HOSTNAMES,
                default=defaults[CONF_NOTIFY_EXCLUDE_HOSTNAMES],
            ): cv.string,
            vol.Optional(
                CONF_HISTORY_RETENTION_DAYS,
                default=defaults[CONF_HISTORY_RETENTION_DAYS],
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_RETENTION_DAYS, max=MAX_RETENTION_DAYS)),
            vol.Optional(
                CONF_HISTORY_MAX_EVENTS, default=defaults[CONF_HISTORY_MAX_EVENTS]
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_MAX_EVENTS, max=MAX_MAX_EVENTS)),
            vol.Optional(CONF_STORE_USERNAMES, default=defaults[CONF_STORE_USERNAMES]): cv.boolean,
            vol.Optional(
                CONF_RESOLVE_HOSTNAMES, default=defaults[CONF_RESOLVE_HOSTNAMES]
            ): cv.boolean,
        }
    )


def _show(flow, step_id: str, defaults: dict, errors: dict | None = None):
    return flow.async_show_form(
        step_id=step_id,
        data_schema=_schema(defaults),
        errors=errors or {},
    )


class AuthenticatedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Authenticated."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return AuthenticatedOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            try:
                stored = storage_from_form(user_input)
            except SettingsError as err:
                return _show(self, "user", user_input, {err.field: err.key})
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Authenticated", data=stored)
        return _show(self, "user", _form_defaults({}))


class AuthenticatedOptionsFlow(OptionsFlow):
    """Reconfigure an existing entry. The framework supplies the config entry."""

    async def async_step_init(self, user_input=None):
        """Edit options and reload."""
        current = merged_mapping(self.config_entry.data, self.config_entry.options)
        if user_input is not None:
            try:
                stored = storage_from_form(user_input)
            except SettingsError as err:
                defaults = _form_defaults(current)
                defaults.update(user_input)
                return _show(self, "init", defaults, {err.field: err.key})
            return self.async_create_entry(title="", data=stored)
        return _show(self, "init", _form_defaults(current))
