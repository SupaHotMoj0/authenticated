"""The Authenticated integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Authenticated config entry."""
    from .runtime import AuthenticatedRuntime, async_reload_entry

    hass.data.setdefault(DOMAIN, {})
    # A YAML platform started earlier would poll and write the same history file.
    yaml_runtime = hass.data[DOMAIN].get("yaml")
    if yaml_runtime is not None:
        await yaml_runtime.async_shutdown()
        hass.data[DOMAIN].pop("yaml", None)

    runtime = AuthenticatedRuntime(hass, entry)
    # The sensor platform is loaded by async_forward_entry_setups and looks up
    # this runtime immediately. Store it before forwarding.
    hass.data[DOMAIN][entry.entry_id] = runtime
    try:
        await runtime.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    except BaseException:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await runtime.async_shutdown()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry and cancel its listeners, tasks, and HTTP session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.async_shutdown()
    return True
