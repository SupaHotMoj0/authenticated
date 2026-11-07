"""IP classification that refuses to treat special ranges as public."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

DOCUMENTATION_NETWORKS = (
    ip_network("192.0.2.0/24"),
    ip_network("198.51.100.0/24"),
    ip_network("203.0.113.0/24"),
    ip_network("2001:db8::/32"),
)
SHARED_NETWORK = ip_network("100.64.0.0/10")

PUBLIC = "public"
DOCUMENTATION = "documentation"
LOOPBACK = "loopback"
LINK_LOCAL = "link_local"
MULTICAST = "multicast"
RESERVED = "reserved"
UNSPECIFIED = "unspecified"
PRIVATE = "private"
SHARED = "shared"
NON_PUBLIC = "non_public"
INVALID = "invalid"


def classify_ip(value: object) -> str:
    """Return a scope name. Only ``public`` may be sent to a geo provider."""
    if not isinstance(value, str):
        return INVALID
    try:
        address = ip_address(value.strip())
    except ValueError:
        return INVALID
    if any(address in network for network in DOCUMENTATION_NETWORKS):
        return DOCUMENTATION
    if address.is_loopback:
        return LOOPBACK
    if address.is_link_local:
        return LINK_LOCAL
    if address.is_multicast:
        return MULTICAST
    if address.is_unspecified:
        return UNSPECIFIED
    if address.is_reserved:
        return RESERVED
    if address.version == 4 and address in SHARED_NETWORK:
        return SHARED
    if address.is_private:
        return PRIVATE
    if address.is_global and not address.is_multicast:
        return PUBLIC
    return NON_PUBLIC


def canonical_ip(value: str) -> str | None:
    """Return the normalized address text, or None when it is not an IP."""
    if classify_ip(value) == INVALID:
        return None
    address = ip_address(value.strip())
    if isinstance(address, (IPv4Address, IPv6Address)):
        return str(address)
    return None


def enrichment_allowed(value: object) -> bool:
    """True only for a globally routable unicast address."""
    return classify_ip(value) == PUBLIC


def address_excluded(value: str, networks: list[str]) -> bool:
    """Return True when the address falls in a configured exclusion."""
    try:
        address = ip_address(value)
    except ValueError:
        return False
    for raw in networks:
        try:
            network = ip_network(raw, strict=False)
        except ValueError:
            continue
        if address in network:
            return True
    return False


def safe_config_relative(value: object) -> str | None:
    """Return a config-relative history path that cannot point at auth storage.

    Absolute paths, parent segments, and anything under ``.storage`` are rejected
    so the history writer cannot be aimed at ``.storage/auth``.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip().replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("~"):
        return None
    parts = tuple(part for part in raw.split("/") if part not in ("", "."))
    if not parts or any(part == ".." or part == ".storage" for part in parts):
        return None
    if any(part.startswith(".") for part in parts[:-1]):
        return None
    return "/".join(parts)
