"""Mock homeassistant before any integration code is imported."""

import sys
from unittest.mock import MagicMock

# These must be injected before pytest collects test files that
# transitively import the integration package (__init__.py -> homeassistant).
_HA_MODS = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.persistent_notification",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.loader",
    "homeassistant.helpers.aiohttp_client",
    "voluptuous",
    "aiohttp",
]

for _mod in _HA_MODS:
    sys.modules.setdefault(_mod, MagicMock())
