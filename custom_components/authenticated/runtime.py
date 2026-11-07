"""Home Assistant adapter. Polls auth storage and owns the enrichment session."""

from __future__ import annotations

import asyncio
import copy
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .auth_source import parse_auth_document
from .history import strip_stored_usernames
from .const import (
    ACTIVITY_SOURCE,
    AUTH_STORAGE,
    BACKUP_SUFFIX,
    NOTIFY_TIMEOUT_SECONDS,
    OBSERVATION_TOKEN_USE,
    POLL_INTERVAL,
    STARTUP,
)
from .lifecycle import Lifecycle
from .notify import async_dispatch
from .observer import (
    apply_geo_result,
    build_snapshot,
    collect_notifications,
    filter_observations,
    hostname_due,
    ingest,
    select_geo_targets,
)
from .providers import async_lookup_ip, create_session
from .settings import Settings, merged_mapping, settings_from_mapping
from .storage_io import (
    read_json_readonly,
    upgrade_and_load,
    write_backup_once,
    write_history,
)
from .time_util import parse_time

_LOGGER = logging.getLogger(__name__)


async def async_reload_entry(hass: HomeAssistant, entry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


class AuthenticatedRuntime:
    """One integration instance."""

    def __init__(self, hass: HomeAssistant, entry=None, yaml_config: dict | None = None) -> None:
        self.hass = hass
        self.entry = entry
        self._yaml = yaml_config
        self.lifecycle = Lifecycle()
        self._lock = asyncio.Lock()
        self._listeners: set = set()
        self.snapshot: dict | None = None
        self._settings: Settings = settings_from_mapping({})
        self._state: dict | None = None
        self._writable = False
        self._legacy_bytes: bytes | None = None
        self._observations: list = []
        self._history_path = ""
        self._backup_path = ""
        self._auth_path = ""

    def add_listener(self, update):
        """Register a sensor callback. The returned function detaches it."""
        self._listeners.add(update)

        def _unsub() -> None:
            self._listeners.discard(update)

        return _unsub

    def _paths(self) -> None:
        self._history_path = self.hass.config.path(self._settings.history_relative)
        self._backup_path = self._history_path + BACKUP_SUFFIX
        self._auth_path = self.hass.config.path(AUTH_STORAGE)

    def _load_settings(self) -> Settings:
        if self._yaml is not None:
            return settings_from_mapping(self._yaml)
        if self.entry is None:
            return settings_from_mapping({})
        return settings_from_mapping(
            merged_mapping(self.entry.data, self.entry.options)
        )

    async def async_start(self) -> None:
        """Load local state, poll once, and schedule the next poll."""
        _LOGGER.info(STARTUP)
        self._settings = self._load_settings()
        self._paths()
        if self._settings.enrich_public_ips:
            self.lifecycle.session = create_session()
        # Local read first so startup does not wait on the geo providers.
        await self._async_poll(include_network=False)
        self.lifecycle.track_task(
            self.hass.async_create_task(self._async_poll(include_network=True))
        )
        self.lifecycle.track_unsub(
            async_track_time_interval(self.hass, self._scheduled, POLL_INTERVAL)
        )

    @callback
    def _scheduled(self, _now) -> None:
        if self.lifecycle.closed:
            return
        self.lifecycle.track_task(
            self.hass.async_create_task(self._async_poll(include_network=True))
        )

    async def async_shutdown(self) -> None:
        """Cancel polling and close the session."""
        await self.lifecycle.async_shutdown()

    async def _async_poll(self, include_network: bool = True) -> None:
        if self.lifecycle.closed or self._lock.locked():
            return
        async with self._lock:
            if self.lifecycle.closed:
                return
            await self._poll_locked(include_network=include_network)

    async def _poll_locked(self, include_network: bool) -> None:
        self._settings = self._load_settings()
        self._paths()
        now = dt_util.utcnow()
        await self._ensure_state(now)
        if self._state is None:
            return
        auth = await self.hass.async_add_executor_job(read_json_readonly, self._auth_path)
        auth_ok = False
        truncated = False
        observations = []
        if auth.error:
            _LOGGER.warning("Auth storage was not read (%s)", auth.error)
        else:
            parsed = parse_auth_document(auth.document)
            if parsed.error:
                _LOGGER.warning("Auth storage was not used (%s)", parsed.error)
            else:
                auth_ok = True
                truncated = parsed.truncated
                observations = filter_observations(parsed.observations, self._settings)
                if parsed.skipped:
                    _LOGGER.debug(
                        "Skipped %s auth records that had no usable last-use fields",
                        parsed.skipped,
                    )
        if auth_ok:
            self._observations = observations
        ingest(
            self._state,
            self._observations if auth_ok else [],
            self._settings,
            now,
            auth_ok=auth_ok,
            truncated=truncated,
        )
        if not self._settings.store_usernames:
            strip_stored_usernames(self._state)
        if include_network and not self.lifecycle.closed:
            await self._enrich(now)
            if not self.lifecycle.closed:
                await self._hostnames(now)
            names = {
                item.user_ref: item.username
                for item in self._observations
                if item.user_ref
            }
            payloads = collect_notifications(
                self._state, self._settings, names, dt_util.utcnow()
            )
            if payloads and not self.lifecycle.closed:
                await self._notify(payloads)
        should_write = self._state.get("bootstrapped") or self._state.get("events")
        if self._writable and should_write and not self.lifecycle.closed:
            await self._persist()
        self.snapshot = build_snapshot(self._observations, self._state)
        self._publish()

    async def _ensure_state(self, now) -> None:
        if self._legacy_bytes is not None:
            payload = self._legacy_bytes
            saved = await self.hass.async_add_executor_job(
                write_backup_once, self._backup_path, payload
            )
            if saved:
                self._legacy_bytes = None
                self._writable = True
        if self._state is not None:
            return

        def _load():
            return upgrade_and_load(
                self._history_path,
                self._backup_path,
                now,
                store_usernames=self._settings.store_usernames,
            )

        loaded = await self.hass.async_add_executor_job(_load)
        if loaded.state is None:
            _LOGGER.error("History file was left unchanged (%s)", loaded.kind)
            self._writable = False
            return
        self._state = loaded.state
        self._writable = loaded.writable
        self._legacy_bytes = loaded.legacy_bytes
        if loaded.kind == "legacy" and loaded.writable:
            await self._persist()
        elif loaded.kind == "legacy_backup_failed":
            _LOGGER.error(
                "History was not upgraded because the rollback copy could not be written"
            )

    async def _persist(self) -> None:
        if self._state is None or not self._writable:
            return
        payload = copy.deepcopy(self._state)
        try:
            await self.hass.async_add_executor_job(write_history, self._history_path, payload)
        except OSError as err:
            _LOGGER.error("History file was not written (%s)", type(err).__name__)

    async def _enrich(self, now) -> None:
        if self._state is None or not self._settings.enrich_public_ips:
            return
        session = self.lifecycle.session
        if session is None:
            session = create_session()
            self.lifecycle.session = session
        targets = select_geo_targets(self._state, self._settings, now)
        if targets:
            _LOGGER.debug("Scheduling geo lookups for %s public addresses", len(targets))
        for ip in targets:
            if self.lifecycle.closed:
                return
            cooldown = parse_time(self._state.get("provider_cooldown_until"))
            if cooldown is not None and dt_util.utcnow() < cooldown:
                break
            result = await async_lookup_ip(session, self._settings.provider, ip)
            if self.lifecycle.closed or self._state is None:
                return
            apply_geo_result(
                self._state,
                ip,
                result,
                provider=self._settings.provider,
                now=dt_util.utcnow(),
            )

    async def _hostnames(self, now) -> None:
        if self._state is None or not self._settings.resolve_hostnames:
            return
        summaries = []
        for observation in self._observations:
            summary = self._state["ip_summaries"].get(observation.ip)
            if isinstance(summary, dict) and hostname_due(summary, self._settings, now):
                summaries.append(summary)
        for summary in summaries[:1]:
            if self.lifecycle.closed:
                return
            host = await self._reverse(summary["ip_address"])
            summary["hostname_checked_at"] = isoformat(dt_util.utcnow())
            if host and host != summary["ip_address"]:
                summary["hostname"] = host[:253]

    async def _reverse(self, ip: str) -> str | None:
        def _lookup() -> str | None:
            import socket

            try:
                host, _aliases, _addresses = socket.gethostbyaddr(ip)
            except OSError:
                return None
            if isinstance(host, str):
                return host
            return None

        try:
            return await asyncio.wait_for(
                self.hass.async_add_executor_job(_lookup), timeout=1
            )
        except (asyncio.TimeoutError, OSError):
            return None

    async def _notify(self, payloads: list[dict]) -> None:
        from homeassistant.components.persistent_notification import async_create

        def _persistent(payload: dict) -> None:
            async_create(
                self.hass,
                payload["message"],
                title=payload["title"],
                notification_id=payload["notification_id"],
            )

        async def _mobile(service: str, payload: dict) -> None:
            await self.hass.services.async_call(
                "notify",
                service,
                {"title": payload["title"], "message": payload["message"]},
                blocking=True,
            )

        await async_dispatch(
            payloads,
            persistent=_persistent,
            mobile=_mobile,
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )

    def _publish(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception as err:
                _LOGGER.debug("Sensor update failed (%s)", type(err).__name__)


def observation_defaults() -> dict:
    """Attributes exposed before any token use has been observed."""
    return {
        "observation_type": OBSERVATION_TOKEN_USE,
        "confirmed_login": False,
        "activity_source": ACTIVITY_SOURCE,
    }
