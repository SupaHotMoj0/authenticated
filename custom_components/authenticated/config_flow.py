"""Config and options flow for Authenticated."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_NOTIFY_EXCLUDE_ASN,
    CONF_NOTIFY_EXCLUDE_HOSTNAMES,
    CONF_NOTIFY_SERVICES,
    DOMAIN,
)
from .form_schema import build_form_schema
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


def _show(flow, step_id: str, defaults: dict, errors: dict | None = None):
    return flow.async_show_form(
        step_id=step_id,
        data_schema=build_form_schema(defaults),
        errors=errors or {},
    )


class AuthenticatedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Authenticated."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow.

        Home Assistant 2026.11 calls this with the entry, then attaches that
        entry before the first step. The flow must not read ``config_entry``
        inside ``__init__``.
        """
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
