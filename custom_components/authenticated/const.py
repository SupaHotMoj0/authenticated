"""Constants for authenticated."""

DOMAIN = "authenticated"
INTEGRATION_VERSION = "1.0.0"
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

# Config options
CONF_NOTIFY = "enable_notification"
CONF_NOTIFY_EXCLUDE_ASN = "notify_exclude_asns"
CONF_NOTIFY_EXCLUDE_HOSTNAMES = "notify_exclude_hostnames"
CONF_EXCLUDE = "exclude"
CONF_EXCLUDE_CLIENTS = "exclude_clients"
CONF_PROVIDER = "provider"
CONF_LOG_LOCATION = "log_location"

# Output file for authenticated IPs
OUTFILE = ".ip_authenticated.yaml"