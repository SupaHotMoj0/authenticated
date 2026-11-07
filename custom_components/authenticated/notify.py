"""Notification delivery with isolated failures."""

from __future__ import annotations

import asyncio
import inspect
import logging

_LOGGER = logging.getLogger(__name__)


async def _invoke(func, *args):
    result = func(*args)
    if inspect.isawaitable(result):
        await result


async def async_dispatch(payloads: list[dict], *, persistent, mobile, timeout: float) -> list[str]:
    """Deliver each channel separately. One failure does not cancel the others.

    Returned codes are channel names and outcomes only. Notification text is not logged.
    """
    outcomes: list[str] = []
    for payload in payloads:
        if payload.get("persistent"):
            try:
                await _invoke(persistent, payload)
                outcomes.append("persistent:ok")
            except Exception as err:  # one channel must not block the rest
                _LOGGER.warning(
                    "Persistent notification failed (%s)", type(err).__name__
                )
                outcomes.append("persistent:error")
        for service in payload.get("services", ()):
            try:
                await asyncio.wait_for(_invoke(mobile, service, payload), timeout=timeout)
                outcomes.append(f"{service}:ok")
            except Exception as err:
                _LOGGER.warning(
                    "Notify service %s failed (%s)", service, type(err).__name__
                )
                outcomes.append(f"{service}:error")
    return outcomes
