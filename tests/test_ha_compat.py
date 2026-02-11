"""Tests for Home Assistant 2026.2 compatibility."""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "custom_components", "authenticated")


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------

def test_manifest_has_required_fields():
    """manifest.json must have all fields required by modern HA."""
    with open(os.path.join(SRC_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    assert manifest["domain"] == "authenticated"
    assert "version" in manifest
    assert "integration_type" in manifest
    assert manifest["integration_type"] in (
        "device", "entity", "hardware", "helper", "hub", "service", "system", "virtual"
    )
    assert "config_flow" in manifest
    assert manifest["config_flow"] is True
    assert "requirements" in manifest
    assert isinstance(manifest["requirements"], list)
    assert "iot_class" in manifest


def test_manifest_version_is_semver():
    """Version must be a valid semver (not prefixed with 'v')."""
    with open(os.path.join(SRC_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    version = manifest["version"]
    # Must not start with 'v' — AwesomeVersion accepts it but HA convention is bare semver
    assert not version.startswith("v"), f"Version should not start with 'v': {version}"
    parts = version.split(".")
    assert len(parts) == 3, f"Version must be semver (x.y.z): {version}"


# ---------------------------------------------------------------------------
# config_flow.py must exist when manifest says config_flow: true
# ---------------------------------------------------------------------------

def test_config_flow_file_exists():
    """config_flow.py must exist when manifest declares config_flow: true."""
    assert os.path.isfile(os.path.join(SRC_DIR, "config_flow.py"))


def test_strings_json_exists():
    """strings.json must exist for config flow UI."""
    assert os.path.isfile(os.path.join(SRC_DIR, "strings.json"))


# ---------------------------------------------------------------------------
# __init__.py must have async_setup_entry and async_unload_entry
# ---------------------------------------------------------------------------

def test_init_has_entry_lifecycle():
    """__init__.py must define async_setup_entry and async_unload_entry."""
    with open(os.path.join(SRC_DIR, "__init__.py")) as f:
        source = f.read()

    assert "async def async_setup_entry" in source, (
        "__init__.py must define async_setup_entry for config entry support"
    )
    assert "async def async_unload_entry" in source, (
        "__init__.py must define async_unload_entry for proper cleanup"
    )


def test_init_forwards_platforms():
    """__init__.py must forward platform setup via async_forward_entry_setups."""
    with open(os.path.join(SRC_DIR, "__init__.py")) as f:
        source = f.read()

    assert "async_forward_entry_setups" in source, (
        "__init__.py should use async_forward_entry_setups (not deprecated async_forward_entry_setup)"
    )


# ---------------------------------------------------------------------------
# sensor.py must use modern HA APIs
# ---------------------------------------------------------------------------

def test_sensor_uses_native_value():
    """sensor.py must use _attr_native_value, not deprecated _attr_state."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "_attr_native_value" in source, (
        "SensorEntity should use _attr_native_value instead of _attr_state"
    )
    # _attr_state should not be set directly
    assert "self._attr_state" not in source, (
        "sensor.py should not set self._attr_state directly; use _attr_native_value"
    )


def test_sensor_has_unique_id():
    """sensor.py must set _attr_unique_id for entity registry."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "_attr_unique_id" in source, (
        "Entity must have a unique_id for the HA entity registry"
    )


def test_sensor_uses_dt_util_not_datetime_utcnow():
    """sensor.py must use homeassistant.util.dt.utcnow(), not datetime.utcnow()."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "datetime.utcnow()" not in source, (
        "datetime.utcnow() is deprecated in Python 3.12+; use homeassistant.util.dt.utcnow()"
    )
    assert "dt_util" in source, (
        "sensor.py should import homeassistant.util.dt as dt_util"
    )


def test_sensor_has_async_setup_entry():
    """sensor.py must have async_setup_entry for config entry platform setup."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "async def async_setup_entry" in source, (
        "sensor.py must define async_setup_entry for config entry support"
    )


def test_sensor_has_has_entity_name():
    """sensor.py entity should set _attr_has_entity_name = True."""
    with open(os.path.join(SRC_DIR, "sensor.py")) as f:
        source = f.read()

    assert "_attr_has_entity_name = True" in source, (
        "Modern HA entities should set _attr_has_entity_name = True"
    )


# ---------------------------------------------------------------------------
# providers.py must have async support
# ---------------------------------------------------------------------------

def test_providers_has_async_method():
    """providers.py must have an async_update_geo_info method."""
    with open(os.path.join(SRC_DIR, "providers.py")) as f:
        source = f.read()

    assert "async def async_update_geo_info" in source, (
        "providers.py should have async_update_geo_info for non-blocking HTTP"
    )
    assert "aiohttp" in source, (
        "providers.py should use aiohttp for async HTTP requests"
    )
