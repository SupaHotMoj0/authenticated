"""Tests for bugs fixed in this changeset."""

import importlib
import os
import sys
from unittest.mock import patch, MagicMock

# Root of the repo (one level up from tests/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Test 1: Import name mismatch (ECLUDE vs EXCLUDE) — the integration must
# import without raising ImportError.
# ---------------------------------------------------------------------------

def test_sensor_imports_correct_const_names():
    """sensor.py must import CONF_NOTIFY_EXCLUDE_ASN and
    CONF_NOTIFY_EXCLUDE_HOSTNAMES (not the misspelled ECLUDE variants)."""
    with open(os.path.join(REPO_ROOT, "sensor.py")) as f:
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
    with open(os.path.join(REPO_ROOT, "const.py")) as f:
        const_source = f.read()
    with open(os.path.join(REPO_ROOT, "sensor.py")) as f:
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

def _get_ipinfo_class():
    """Import IPInfo by setting up the package context so relative imports work."""
    # Create a fake parent package so `from . import ...` resolves
    fake_pkg = MagicMock()
    fake_pkg.AuthenticatedBaseException = type("AuthenticatedBaseException", (Exception,), {})
    sys.modules["authenticated_pkg"] = fake_pkg

    spec = importlib.util.spec_from_file_location(
        "authenticated_pkg.providers",
        os.path.join(REPO_ROOT, "providers.py"),
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    # Patch the relative import target
    mod.__package__ = "authenticated_pkg"
    spec.loader.exec_module(mod)
    return mod.IPInfo


def test_ipinfo_org_no_space():
    """IPInfo.org must return None when the org field has no space separator."""
    IPInfo = _get_ipinfo_class()
    provider = IPInfo("1.1.1.1")
    provider.result = {"org": "AS13335"}

    assert provider.org is None
    assert provider.asn == "AS13335"


def test_ipinfo_org_with_space():
    """IPInfo.org must return the org name after the ASN prefix."""
    IPInfo = _get_ipinfo_class()
    provider = IPInfo("1.1.1.1")
    provider.result = {"org": "AS13335 Cloudflare Inc"}

    assert provider.asn == "AS13335"
    assert provider.org == "Cloudflare Inc"


def test_ipinfo_org_empty():
    """IPInfo.org must return None when org is missing."""
    IPInfo = _get_ipinfo_class()
    provider = IPInfo("1.1.1.1")
    provider.result = {}

    assert provider.org is None
    assert provider.asn is None


# ---------------------------------------------------------------------------
# Test 3: Blocking I/O — verify that async_handle_auth_event wraps blocking
# calls with async_add_executor_job.
# ---------------------------------------------------------------------------

def test_async_handle_auth_event_uses_executor_for_blocking_calls():
    """sensor.py must wrap lookup() and get_hostname() in
    async_add_executor_job inside async_handle_auth_event."""
    with open(os.path.join(REPO_ROOT, "sensor.py")) as f:
        source = f.read()

    method_start = source.index("async def async_handle_auth_event")
    next_def = source.index("\n    async def ", method_start + 1)
    method_body = source[method_start:next_def]

    assert "async_add_executor_job(ipdata.lookup)" in method_body, (
        "ipdata.lookup() should be called via async_add_executor_job"
    )
    assert "async_add_executor_job(get_hostname" in method_body, (
        "get_hostname() should be called via async_add_executor_job"
    )

    stripped = method_body.replace("async_add_executor_job(ipdata.lookup)", "")
    assert "ipdata.lookup()" not in stripped, (
        "ipdata.lookup() is called synchronously somewhere in async_handle_auth_event"
    )
