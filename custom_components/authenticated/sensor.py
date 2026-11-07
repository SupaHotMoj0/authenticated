"""Sensor for the latest observed refresh-token use."""

from __future__ import annotations

import logging

import probatio as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.config_validation as cv

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
    DOMAIN,
    MAX_MAX_EVENTS,
    MAX_RETENTION_DAYS,
    MIN_MAX_EVENTS,
    MIN_RETENTION_DAYS,
    NOTIFY_ON_CHOICES,
)
from .providers import PROVIDERS
from .runtime import AuthenticatedRuntime, observation_defaults

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_PROVIDER, default="ipapi"): vol.In(list(PROVIDERS)),
        vol.Optional(CONF_LOG_LOCATION, default=""): cv.string,
        vol.Optional(CONF_NOTIFY, default=True): cv.boolean,
        vol.Optional(CONF_NOTIFY_SERVICES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_NOTIFY_ON, default="new_ip"): vol.In(NOTIFY_ON_CHOICES),
        vol.Optional(CONF_NOTIFY_EXCLUDE_ASN, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_NOTIFY_EXCLUDE_HOSTNAMES, default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(CONF_EXCLUDE, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUDE_CLIENTS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_HISTORY_RETENTION_DAYS, default=30): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_RETENTION_DAYS, max=MAX_RETENTION_DAYS)
        ),
        vol.Optional(CONF_HISTORY_MAX_EVENTS, default=200): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_MAX_EVENTS, max=MAX_MAX_EVENTS)
        ),
        vol.Optional(CONF_STORE_USERNAMES, default=False): cv.boolean,
        vol.Optional(CONF_ENRICH_PUBLIC_IPS, default=True): cv.boolean,
        vol.Optional(CONF_RESOLVE_HOSTNAMES, default=False): cv.boolean,
    }
)

_ATTRIBUTION = {
    "ipapi": "Public IP details are requested from ipapi.co when enrichment is enabled.",
    "ipinfo": "Public IP details are requested from ipinfo.io when enrichment is enabled.",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AuthenticatedSensor(runtime, entry.entry_id)])


async def async_setup_platform(
    hass: HomeAssistant,
    config,
    async_add_entities,
    discovery_info=None,
):
    """Set up the legacy YAML platform.

    A config entry already owns polling and the history file. Starting a second
    runtime would observe the same tokens twice, so YAML yields in that case.
    """
    if hass.config_entries.async_entries(DOMAIN):
        _LOGGER.warning(
            "The YAML authenticated platform was not started because the integration is already configured"
        )
        return
    runtime = AuthenticatedRuntime(hass, yaml_config=config)
    hass.data.setdefault(DOMAIN, {})["yaml"] = runtime

    async def _stop(_event) -> None:
        await runtime.async_shutdown()
        hass.data.get(DOMAIN, {}).pop("yaml", None)

    hass.bus.async_listen_once("homeassistant_stop", _stop)
    await runtime.async_start()
    async_add_entities([AuthenticatedSensor(runtime, "yaml")])


def _render(snapshot: dict | None) -> tuple[str | None, dict, str]:
    base = observation_defaults()
    if not snapshot:
        return None, base, _ATTRIBUTION["ipapi"]
    attributes = {
        **base,
        "hostname": snapshot.get("hostname"),
        "country": snapshot.get("country"),
        "country_code": snapshot.get("country_code"),
        "region": snapshot.get("region"),
        "city": snapshot.get("city"),
        "asn": snapshot.get("asn"),
        "org": snapshot.get("org"),
        "latitude": snapshot.get("latitude"),
        "longitude": snapshot.get("longitude"),
        "timezone": snapshot.get("timezone"),
        "currency": snapshot.get("currency"),
        "languages": snapshot.get("languages"),
        "postal": snapshot.get("postal"),
        "username": snapshot.get("username"),
        "new_ip": snapshot.get("new_ip"),
        "last_authenticated_time": snapshot.get("last_used_at"),
        "previous_authenticated_time": snapshot.get("prev_used_at"),
        "last_observed_at": snapshot.get("last_observed_at"),
        "ip_scope": snapshot.get("ip_scope"),
        "geo_status": snapshot.get("geo_status"),
        "geo_provider": snapshot.get("geo_provider"),
        "token_type": snapshot.get("token_type"),
        "history_count": snapshot.get("history_count"),
    }
    provider = snapshot.get("geo_provider")
    attribution = _ATTRIBUTION.get(provider, _ATTRIBUTION["ipapi"])
    return snapshot.get("ip_address"), attributes, attribution


class AuthenticatedSensor(SensorEntity):
    """Latest address seen on a refresh token."""

    _attr_icon = "mdi:lock-alert"
    _attr_has_entity_name = True
    _attr_name = "Last successful authentication"
    _attr_should_poll = False

    def __init__(self, runtime: AuthenticatedRuntime, entry_id: str) -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{DOMAIN}_last_auth_{entry_id}"
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Subscribe, and detach the subscription when the entity is removed."""
        self.async_on_remove(self._runtime.add_listener(self._handle_update))
        self._handle_update()

    def _handle_update(self) -> None:
        state, attributes, attribution = _render(self._runtime.snapshot)
        if (
            state == self._attr_native_value
            and attributes == self._attr_extra_state_attributes
            and attribution == self._attr_attribution
        ):
            return
        self._attr_native_value = state
        self._attr_extra_state_attributes = attributes
        self._attr_attribution = attribution
        if self.hass is not None:
            self.async_write_ha_state()
