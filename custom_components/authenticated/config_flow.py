"""Config flow for Authenticated integration."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_NOTIFY,
    CONF_NOTIFY_EXCLUDE_ASN,
    CONF_NOTIFY_EXCLUDE_HOSTNAMES,
    CONF_PROVIDER,
    DOMAIN,
)
from .providers import PROVIDERS


class AuthenticatedConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Authenticated."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # Prevent duplicate entries
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Authenticated",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PROVIDER, default="ipapi"): vol.In(
                        list(PROVIDERS.keys())
                    ),
                    vol.Optional(CONF_NOTIFY, default=True): cv.boolean,
                    vol.Optional(CONF_EXCLUDE, default=""): cv.string,
                    vol.Optional(CONF_EXCLUDE_CLIENTS, default=""): cv.string,
                    vol.Optional(CONF_NOTIFY_EXCLUDE_ASN, default=""): cv.string,
                    vol.Optional(CONF_NOTIFY_EXCLUDE_HOSTNAMES, default=""): cv.string,
                }
            ),
        )
