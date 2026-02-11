"""Authenticated login sensor - async, event-driven, extended."""

import logging
import os
import socket
from ipaddress import ip_address, ip_network
from datetime import datetime, timedelta
from contextlib import suppress

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.components.persistent_notification import async_create

from .const import (
    CONF_EXCLUDE,
    CONF_EXCLUDE_CLIENTS,
    CONF_LOG_LOCATION,
    CONF_NOTIFY,
    CONF_NOTIFY_ECLUDE_ASN,
    CONF_NOTIFY_ECLUDE_HOSTNAMES,
    CONF_PROVIDER,
    OUTFILE,
    STARTUP,
)
from .providers import PROVIDERS

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_PROVIDER, default="ipapi"): vol.In(list(PROVIDERS.keys())),
        vol.Optional(CONF_LOG_LOCATION, default=""): cv.string,
        vol.Optional(CONF_NOTIFY, default=True): cv.boolean,
        vol.Optional(CONF_NOTIFY_ECLUDE_ASN, default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(CONF_NOTIFY_ECLUDE_HOSTNAMES, default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(CONF_EXCLUDE, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUDE_CLIENTS, default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
    }
)

# ------------------------
# Helper functions
# ------------------------
def humanize_time(timestring):
    return datetime.strptime(timestring[:19], "%Y-%m-%dT%H:%M:%S")


def is_public(ip):
    try:
        ip_obj = ip_address(ip)
        return not (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved)
    except Exception:
        return False


def get_hostname(ip):
    if ip.startswith("127.") or ip == "::1":
        return "localhost"
    with suppress(Exception):
        hostname = socket.getfqdn(ip)
        if hostname and hostname != ip:
            return hostname
    return "unknown"


# ------------------------
# Async File I/O
# ------------------------
async def async_get_outfile_content(hass, file):
    import yaml

    def _read():
        if not os.path.exists(file):
            return {}
        with open(file) as f:
            return yaml.safe_load(f) or {}

    return await hass.async_add_executor_job(_read)


async def async_write_outfile(hass, file, data):
    import yaml

    def _write():
        with open(file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, explicit_start=True)

    await hass.async_add_executor_job(_write)


# ------------------------
# Setup platform
# ------------------------
async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    _LOGGER.info(STARTUP)

    notify = config.get(CONF_NOTIFY)
    notify_exclude_asn = config.get(CONF_NOTIFY_ECLUDE_ASN)
    notify_exclude_hostnames = config.get(CONF_NOTIFY_ECLUDE_HOSTNAMES)
    exclude = config.get(CONF_EXCLUDE)
    exclude_clients = config.get(CONF_EXCLUDE_CLIENTS)
    provider = config.get(CONF_PROVIDER)

    hass.data["authenticated"] = {}
    out_file = hass.config.path(OUTFILE)

    sensor = AuthenticatedSensor(
        hass,
        notify,
        out_file,
        exclude,
        exclude_clients,
        notify_exclude_asn,
        notify_exclude_hostnames,
        provider,
    )

    await sensor.async_initial_run()
    async_add_entities([sensor], True)

    # Listen to HA auth events for real-time logins
    hass.bus.async_listen(
        "homeassistant_auth",
        lambda event: hass.async_create_task(sensor.async_handle_auth_event(event)),
    )


# ------------------------
# Sensor Entity
# ------------------------
class AuthenticatedSensor(SensorEntity):
    _attr_icon = "mdi:lock-alert"
    _attr_name = "Last successful authentication"

    def __init__(
        self,
        hass,
        notify,
        out,
        exclude,
        exclude_clients,
        notify_exclude_asn,
        notify_exclude_hostnames,
        provider,
    ):
        self.hass = hass
        self.provider = provider
        self.stored = {}
        self.last_ip = None
        self.exclude = exclude
        self.exclude_clients = exclude_clients
        self.notify = notify
        self.notify_exclude_asn = notify_exclude_asn
        self.notify_exclude_hostnames = notify_exclude_hostnames
        self.out = out
        self._attr_state = None
        self.all_users = {}

    async def async_initial_run(self):
        self.all_users, tokens = await async_load_authentications(
            self.hass, ".storage/auth", self.exclude, self.exclude_clients
        )

        self.stored = await async_get_outfile_content(self.hass, self.out)

        for ip, attrs in tokens.items():
            if not is_public(ip):
                continue
            access_data = AuthenticatedData(ip, attrs)
            ipdata = IPData(access_data, self.all_users, self.provider, new=False)
            if ip not in self.stored:
                ipdata.lookup()
            self.hass.data["authenticated"][ip] = ipdata

        await self.async_write_to_file()

        if self.hass.data["authenticated"]:
            last_ip = max(
                self.hass.data["authenticated"].values(),
                key=lambda x: x.last_used_at or "",
            )
            self.last_ip = last_ip
            self._attr_state = last_ip.ip_address

    async def async_handle_auth_event(self, event):
        data = event.data
        ip = data.get("ip_address")
        user_id = data.get("user_id")
        if not ip or not is_public(ip):
            return

        if ip in self.hass.data["authenticated"]:
            ipdata = self.hass.data["authenticated"][ip]
            ipdata.prev_used_at = ipdata.last_used_at
            ipdata.last_used_at = datetime.utcnow().isoformat()
        else:
            access_data = AuthenticatedData(
                ip,
                {
                    "user_id": user_id,
                    "last_used_at": datetime.utcnow().isoformat(),
                    "prev_used_at": None,
                },
            )
            ipdata = IPData(access_data, self.all_users, self.provider)
            ipdata.lookup()
            self.hass.data["authenticated"][ip] = ipdata

        ipdata.hostname = get_hostname(ip)
        self.last_ip = ipdata
        self._attr_state = ipdata.ip_address

        if self.notify:
            if ipdata.asn not in self.notify_exclude_asn and ipdata.hostname not in self.notify_exclude_hostnames:
                ipdata.notify(self.hass)
            ipdata.new_ip = False

        await self.async_write_to_file()
        self.async_write_ha_state()

    async def async_update(self):
        await self.async_initial_run()

    @property
    def extra_state_attributes(self):
        if self.last_ip is None:
            return None
        return {
            "hostname": self.last_ip.hostname,
            "country": self.last_ip.country,
            "country_code": self.last_ip.country_code,
            "region": self.last_ip.region,
            "city": self.last_ip.city,
            "asn": self.last_ip.asn,
            "org": self.last_ip.org,
            "latitude": self.last_ip.latitude,
            "longitude": self.last_ip.longitude,
            "timezone": self.last_ip.timezone,
            "currency": self.last_ip.currency,
            "languages": self.last_ip.languages,
            "postal": self.last_ip.postal,
            "username": self.last_ip.username,
            "new_ip": self.last_ip.new_ip,
            "last_authenticated_time": self.last_ip.last_used_at,
            "previous_authenticated_time": self.last_ip.prev_used_at,
        }

    async def async_write_to_file(self):
        info = await async_get_outfile_content(self.hass, self.out)
        for ip, data in self.hass.data["authenticated"].items():
            info[ip] = {
                "user_id": data.user_id,
                "username": data.username,
                "last_used_at": data.last_used_at,
                "prev_used_at": data.prev_used_at,
                "country": data.country,
                "country_code": data.country_code,
                "region": data.region,
                "city": data.city,
                "asn": data.asn,
                "org": data.org,
                "latitude": data.latitude,
                "longitude": data.longitude,
                "timezone": data.timezone,
                "currency": data.currency,
                "languages": data.languages,
                "postal": data.postal,
                "hostname": data.hostname,
            }
        await async_write_outfile(self.hass, self.out, info)


# ------------------------
# Auth / IPData classes
# ------------------------
async def async_load_authentications(hass, authfile_path, exclude, exclude_clients):
    import json

    file_path = hass.config.path(authfile_path)
    if not os.path.exists(file_path):
        _LOGGER.critical("Auth file missing: %s", file_path)
        return {}, {}

    def _load_file():
        with open(file_path) as f:
            return json.load(f)

    auth = await hass.async_add_executor_job(_load_file)

    users = {u["id"]: u["name"] for u in auth["data"]["users"]}
    tokens_cleaned = {}
    for t in auth["data"]["refresh_tokens"]:
        try:
            ip = t.get("last_used_ip")
            if ip is None or not is_public(ip):
                continue
            if any(ip_address(ip) in ip_network(net, strict=False) for net in exclude):
                continue
            if t.get("client_id") in exclude_clients:
                continue
            if ip in tokens_cleaned:
                if t["last_used_at"] > tokens_cleaned[ip]["last_used_at"]:
                    tokens_cleaned[ip]["last_used_at"] = t["last_used_at"]
                    tokens_cleaned[ip]["user_id"] = t["user_id"]
            else:
                tokens_cleaned[ip] = {"last_used_at": t["last_used_at"], "user_id": t["user_id"]}
        except Exception:
            continue
    return users, tokens_cleaned


class AuthenticatedData:
    def __init__(self, ipaddr, attributes):
        self.ipaddr = ipaddr
        self.attributes = attributes
        self.last_access = attributes.get("last_used_at")
        self.prev_access = attributes.get("prev_used_at")
        self.country = attributes.get("country")
        self.country_code = attributes.get("country_code")
        self.region = attributes.get("region")
        self.city = attributes.get("city")
        self.asn = attributes.get("asn")
        self.org = attributes.get("org")
        self.latitude = attributes.get("latitude")
        self.longitude = attributes.get("longitude")
        self.timezone = attributes.get("timezone")
        self.currency = attributes.get("currency")
        self.languages = attributes.get("languages")
        self.postal = attributes.get("postal")
        self.user_id = attributes.get("user_id")
        self.hostname = attributes.get("hostname")


class IPData:
    def __init__(self, access_data, users, provider, new=True):
        self.all_users = users
        self.provider = provider
        self.ip_address = access_data.ipaddr
        self.last_used_at = access_data.last_access
        self.prev_used_at = access_data.prev_access
        self.user_id = access_data.user_id
        self.hostname = access_data.hostname
        self.country = access_data.country
        self.country_code = access_data.country_code
        self.region = access_data.region
        self.city = access_data.city
        self.asn = access_data.asn
        self.org = access_data.org
        self.latitude = access_data.latitude
        self.longitude = access_data.longitude
        self.timezone = access_data.timezone
        self.currency = access_data.currency
        self.languages = access_data.languages
        self.postal = access_data.postal
        self.new_ip = new

    @property
    def username(self):
        return self.all_users.get(self.user_id, "Unknown") if self.user_id else "Unknown"

    def lookup(self):
        geo = PROVIDERS[self.provider](self.ip_address)
        geo.update_geo_info()
        if geo.computed_result:
            self.country = geo.computed_result.get("country")
            self.country_code = geo.computed_result.get("country_code")
            self.region = geo.computed_result.get("region")
            self.city = geo.computed_result.get("city")
            self.asn = geo.computed_result.get("asn")
            self.org = geo.computed_result.get("org")
            self.latitude = geo.computed_result.get("latitude")
            self.longitude = geo.computed_result.get("longitude")
            self.timezone = geo.computed_result.get("timezone")
            self.currency = geo.computed_result.get("currency")
            self.languages = geo.computed_result.get("languages")
            self.postal = geo.computed_result.get("postal")

    def notify(self, hass):
        message = f"**IP Address:** {self.ip_address}\n**Username:** {self.username}\n"
        for val, name in [
            (self.country, "Country"),
            (self.country_code, "Country Code"),
            (self.region, "Region"),
            (self.city, "City"),
            (self.asn, "ASN"),
            (self.org, "Organisation"),
            (self.latitude, "Latitude"),
            (self.longitude, "Longitude"),
            (self.timezone, "Timezone"),
            (self.currency, "Currency"),
            (self.languages, "Languages"),
            (self.postal, "Postal"),
            (self.hostname, "Hostname"),
        ]:
            if val:
                message += f"**{name}:** {val}\n"
        if self.last_used_at:
            message += f"**Login time:** {self.last_used_at[:19].replace('T', ' ')}\n"
        async_create(hass, message, title="New successful login", notification_id=self.ip_address)