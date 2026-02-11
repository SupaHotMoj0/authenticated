"""Providers."""

import logging
import requests
from . import AuthenticatedBaseException

_LOGGER = logging.getLogger(__name__)

PROVIDERS = {}


def register_provider(classname):
    """Register providers when used as a decorator."""
    PROVIDERS[classname.name] = classname
    return classname


class GeoProvider:
    """Base class for Geo Providers."""

    url = None

    def __init__(self, ipaddr):
        self.ipaddr = ipaddr
        self.result = {}

    def update_geo_info(self):
        """Fetch and parse geo information."""
        self.result = {}
        try:
            api = self.url.format(self.ipaddr)
            data = requests.get(api, timeout=5).json()
            _LOGGER.debug(f"Geo data for {self.ipaddr}: {data}")

            if data.get("error"):
                if data.get("reason") == "RateLimited":
                    raise AuthenticatedBaseException(
                        "RatelimitError, try a different provider."
                    )
            elif data.get("status", "success") in ["error", "fail"] or data.get("reserved"):
                return

            self.result = data
        except AuthenticatedBaseException as exception:
            _LOGGER.error(exception)
        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"Request failed for {self.ipaddr}: {e}")

    @property
    def computed_result(self):
        """Return parsed result dictionary."""
        if self.result:
            return {
                "country": self.country,
                "region": self.region,
                "city": self.city,
                "asn": self.asn,
                "org": self.org,
                "latitude": self.latitude,
                "longitude": self.longitude,
                "timezone": self.timezone,
                "currency": self.currency,
                "languages": self.languages,
                "postal": self.postal,
                "country_code": self.country_code,
            }
        return None

    # Default properties to override
    @property
    def country(self):
        return self.result.get("country_name")

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
    """IPApi provider."""

    url = "https://ipapi.co/{}/json"
    name = "ipapi"


@register_provider
class IPInfo(GeoProvider):
    """IPInfo provider."""

    url = "https://ipinfo.io/{}/json"
    name = "ipinfo"

    @property
    def asn(self):
        org = self.result.get("org")
        return org.split(" ", 1)[0] if org else None

    @property
    def org(self):
        org = self.result.get("org")
        if not org:
            return None
        parts = org.split(" ", 1)
        return parts[1] if len(parts) > 1 else None