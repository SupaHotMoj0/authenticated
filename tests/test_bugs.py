"""Tests for bugs fixed in this changeset."""

import os

from custom_components.authenticated.providers import IPInfo

# Root of the repo and integration source directory
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "custom_components", "authenticated")


# ---------------------------------------------------------------------------
# Test 1: Import name mismatch (ECLUDE vs EXCLUDE) — the integration must
# import without raising ImportError.
# ---------------------------------------------------------------------------

def test_sensor_imports_correct_const_names():
    """sensor.py must import CONF_NOTIFY_EXCLUDE_ASN and
    CONF_NOTIFY_EXCLUDE_HOSTNAMES (not the misspelled ECLUDE variants)."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "CONF_NOTIFY_ECLUDE_ASN" not in source, (
        "sensor.py still references the misspelled CONF_NOTIFY_ECLUDE_ASN"
    )
    assert "CONF_NOTIFY_ECLUDE_HOSTNAMES" not in source, (
        "sensor.py still references the misspelled CONF_NOTIFY_ECLUDE_HOSTNAMES"
    )

    assert "CONF_NOTIFY_EXCLUDE_ASN" in source
    assert "CONF_NOTIFY_EXCLUDE_HOSTNAMES" in source


def test_const_exports_match_sensor_imports():
    """The names exported by const.py must include every CONF_ name
    referenced in sensor.py imports."""
    with open(os.path.join(SRC_DIR, "const.py")) as f:
        const_source = f.read()
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        sensor_source = f.read()

    import_block_start = sensor_source.index("from .const import (")
    import_block_end = sensor_source.index(")", import_block_start)
    import_block = sensor_source[import_block_start:import_block_end]

    for line in import_block.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("CONF_"):
            assert f"{line} =" in const_source or f"{line}=" in const_source, (
                f"sensor.py imports {line} but const.py does not define it"
            )


# ---------------------------------------------------------------------------
# Test 2: IPInfo provider — org property must not crash when the org string
# has no space (e.g. "AS13335" with no org name after it).
# ---------------------------------------------------------------------------

def test_ipinfo_org_no_space():
    """IPInfo.org must return None when the org field has no space separator."""
    provider = IPInfo("203.0.113.10")
    provider.result = {"org": "AS64500"}

    assert provider.org is None
    assert provider.asn == "AS64500"


def test_ipinfo_org_with_space():
    """IPInfo.org must return the org name after the ASN prefix."""
    provider = IPInfo("203.0.113.10")
    provider.result = {"org": "AS64500 Example Operator"}

    assert provider.asn == "AS64500"
    assert provider.org == "Example Operator"


def test_ipinfo_org_empty():
    """IPInfo.org must return None when org is missing."""
    provider = IPInfo("203.0.113.10")
    provider.result = {}

    assert provider.org is None
    assert provider.asn is None


# ---------------------------------------------------------------------------
# Test 3: Blocking I/O — verify that async_handle_auth_event wraps blocking
# calls with async_add_executor_job.
# ---------------------------------------------------------------------------

def test_async_handle_auth_event_uses_executor_for_blocking_calls():
    """Geo lookup is async and the old bus listener is not left registered.

    Home Assistant does not emit a reliable login event. The previous
    ``homeassistant_auth`` listener never ran and was not removed on unload.
    """
    sources = []
    for name in os.listdir(SRC_DIR):
        if name.endswith(".py"):
            with open(os.path.join(SRC_DIR, name), encoding="utf-8") as handle:
                sources.append(handle.read())
    combined = "\n".join(sources)
    assert "import requests" not in combined
    assert "requests.get" not in combined
    assert "async_listen(" not in combined
    assert "X-Forwarded-For" not in combined
    assert "async def async_lookup_ip" in combined
    assert "async def async_shutdown" in combined
    init = next(source for source in sources if "async def async_unload_entry" in source)
    assert "async_shutdown" in init
