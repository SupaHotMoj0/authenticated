"""Constants for the Authenticated integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "authenticated"
INTEGRATION_VERSION = "1.1.0"
ISSUE_URL = "https://github.com/SupaHotMoj0/authenticated/issues"

STARTUP = f"""
-------------------------------------------------------------------
{DOMAIN}
Version: {INTEGRATION_VERSION}
This is a custom component
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

CONF_NOTIFY = "enable_notification"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_ON = "notify_on"
CONF_NOTIFY_EXCLUDE_ASN = "notify_exclude_asns"
CONF_NOTIFY_EXCLUDE_HOSTNAMES = "notify_exclude_hostnames"
CONF_EXCLUDE = "exclude"
CONF_EXCLUDE_CLIENTS = "exclude_clients"
CONF_PROVIDER = "provider"
CONF_LOG_LOCATION = "log_location"
CONF_HISTORY_RETENTION_DAYS = "history_retention_days"
CONF_HISTORY_MAX_EVENTS = "history_max_events"
CONF_STORE_USERNAMES = "store_usernames"
CONF_ENRICH_PUBLIC_IPS = "enrich_public_ips"
CONF_RESOLVE_HOSTNAMES = "resolve_hostnames"

NOTIFY_ON_NEW_IP = "new_ip"
NOTIFY_ON_EVERY = "every_observation"
NOTIFY_ON_CHOICES = (NOTIFY_ON_NEW_IP, NOTIFY_ON_EVERY)

PROVIDER_IPAPI = "ipapi"
PROVIDER_IPINFO = "ipinfo"
PROVIDERS = (PROVIDER_IPAPI, PROVIDER_IPINFO)

OUTFILE = ".ip_authenticated.yaml"
BACKUP_SUFFIX = ".v1.bak"
AUTH_STORAGE = ".storage/auth"
HISTORY_VERSION = 2

POLL_INTERVAL = timedelta(seconds=60)
TOKEN_OBSERVATION_CAP = 500

DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_EVENTS = 200
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365
MIN_MAX_EVENTS = 10
MAX_MAX_EVENTS = 1000
LIST_LIMIT = 50
TEXT_LIMIT = 256
NOTIFY_SERVICE_LIMIT = 8
NOTIFY_TIMEOUT_SECONDS = 10

GEO_MAX_ATTEMPTS = 4
GEO_BACKOFF_BASE_SECONDS = 60
GEO_BACKOFF_CAP_SECONDS = 6 * 60 * 60
GEO_NEGATIVE_TTL_SECONDS = 24 * 60 * 60
GEO_SUCCESS_TTL_SECONDS = 7 * 24 * 60 * 60
GEO_MAX_PER_POLL = 3
GEO_RESPONSE_BYTES = 65536
PROVIDER_COOLDOWN_SECONDS = 15 * 60
HOSTNAME_TTL_SECONDS = 24 * 60 * 60

OBSERVATION_TOKEN_USE = "token_use"
ACTIVITY_SOURCE = "auth_storage_refresh_tokens"

USER_AGENT = f"AuthenticatedHomeAssistant/{INTEGRATION_VERSION}"

GEO_FIELDS = (
    "country",
    "country_code",
    "region",
    "city",
    "asn",
    "org",
    "latitude",
    "longitude",
    "timezone",
    "currency",
    "languages",
    "postal",
)

# Copied from auth storage only as an explicit skip list. These values must
# never be stored, logged, or forwarded.
AUTH_SECRET_KEYS = frozenset(
    {
        "token",
        "jwt_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
    }
)
