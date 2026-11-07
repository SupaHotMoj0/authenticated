"""Versioned local history of observed token uses.

Version 1 was a mapping of IP address to the latest fields. Version 2 keeps a
bounded event list plus a per-address summary. Usernames are omitted unless the
option is on. Raw auth secrets are never accepted into this document.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .const import (
    GEO_FIELDS,
    HISTORY_VERSION,
    TEXT_LIMIT,
)
from .ip_util import canonical_ip, classify_ip
from .time_util import isoformat, parse_time, user_ref


def empty_state(now: datetime) -> dict:
    """Return a new version-2 document."""
    return {
        "version": HISTORY_VERSION,
        "bootstrapped": False,
        "updated_at": isoformat(now),
        "provider_cooldown_until": None,
        "tokens": {},
        "ip_summaries": {},
        "events": [],
        "pending_notifications": [],
    }


def _text(value: object, limit: int = TEXT_LIMIT) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def _coord(value: object, limit: float) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) > limit:
        return None
    return number


def geo_from_mapping(mapping: object) -> dict:
    """Copy only known geo fields."""
    source = mapping if isinstance(mapping, dict) else {}
    return {
        "country": _text(source.get("country")),
        "country_code": _text(source.get("country_code"), 8),
        "region": _text(source.get("region")),
        "city": _text(source.get("city")),
        "asn": _text(source.get("asn"), 64),
        "org": _text(source.get("org")),
        "latitude": _coord(source.get("latitude"), 90),
        "longitude": _coord(source.get("longitude"), 180),
        "timezone": _text(source.get("timezone"), 64),
        "currency": _text(source.get("currency"), 16),
        "languages": _text(source.get("languages")),
        "postal": _text(source.get("postal"), 32),
    }


def geo_is_populated(fields: dict) -> bool:
    """True when a lookup returned something worth keeping."""
    return any(fields.get(field) not in (None, "", []) for field in GEO_FIELDS)


def blank_summary(ip: str, scope: str) -> dict:
    """Summary shell for an address."""
    summary = {
        "ip_address": ip,
        "ip_scope": scope,
        "user_ref": None,
        "last_used_at": None,
        "prev_used_at": None,
        "last_observed_at": None,
        "latest_was_new_ip": False,
        "hostname": None,
        "hostname_checked_at": None,
        "geo_status": "skipped" if scope != "public" else "incomplete",
        "geo_attempts": 0,
        "geo_next_attempt_at": None,
        "geo_checked_at": None,
        "geo_provider": None,
        "token_type": None,
    }
    summary.update(geo_from_mapping({}))
    return summary


def _legacy_geo_status(fields: dict, scope: str) -> str:
    if scope != "public":
        return "skipped"
    if geo_is_populated(fields):
        return "complete"
    return "incomplete"


def migrate_legacy(document: dict, now: datetime, *, store_usernames: bool) -> dict:
    """Convert a version-1 IP map. Existing rows are seeded, not re-notified.

    Usernames are copied only when the option is enabled. The original file
    bytes are the rollback copy; this document does not keep auth secrets.
    """
    state = empty_state(now)
    state["bootstrapped"] = True
    for key, value in document.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        ip = canonical_ip(key)
        if ip is None:
            continue
        scope = classify_ip(ip)
        summary = blank_summary(ip, scope)
        fields = geo_from_mapping(value)
        summary.update(fields)
        summary["geo_status"] = _legacy_geo_status(fields, scope)
        if summary["geo_status"] == "complete":
            summary["geo_checked_at"] = isoformat(now)
        summary["last_used_at"] = _text(value.get("last_used_at"), 64)
        summary["prev_used_at"] = _text(value.get("prev_used_at"), 64)
        user_id = value.get("user_id")
        if isinstance(user_id, str) and user_id:
            summary["user_ref"] = user_ref(user_id)
        if store_usernames:
            summary["username"] = _text(value.get("username"), 128)
        hostname = _text(value.get("hostname"), 253)
        if hostname and hostname.lower() != "unknown":
            summary["hostname"] = hostname
        state["ip_summaries"][ip] = summary
    return state


def classify_document(document: object) -> str:
    """Return missing, invalid, legacy, or v2."""
    if document is None:
        return "missing"
    if not isinstance(document, dict):
        return "invalid"
    if not document:
        return "missing"
    if document.get("version") == HISTORY_VERSION:
        if isinstance(document.get("events"), list) and isinstance(
            document.get("ip_summaries"), dict
        ):
            return "v2"
        return "invalid"
    if "version" in document or "events" in document:
        return "invalid"
    if all(isinstance(value, dict) for value in document.values()):
        return "legacy"
    return "invalid"


def sanitize_v2(document: dict, now: datetime) -> dict:
    """Rebuild a stored v2 document from the known keys."""
    state = empty_state(now)
    state["bootstrapped"] = bool(document.get("bootstrapped"))
    cooldown = document.get("provider_cooldown_until")
    state["provider_cooldown_until"] = cooldown if parse_time(cooldown) else None
    tokens = document.get("tokens")
    if isinstance(tokens, dict):
        for key, value in tokens.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            used = value.get("last_used_at")
            ip = canonical_ip(value.get("ip")) if isinstance(value.get("ip"), str) else None
            if not isinstance(used, str) or ip is None:
                continue
            state["tokens"][key[:64]] = {"last_used_at": used[:64], "ip": ip}
    summaries = document.get("ip_summaries")
    if isinstance(summaries, dict):
        for key, value in summaries.items():
            if not isinstance(value, dict):
                continue
            ip = canonical_ip(key) if isinstance(key, str) else None
            if ip is None:
                continue
            scope = classify_ip(ip)
            summary = blank_summary(ip, scope)
            summary.update(geo_from_mapping(value))
            for field in (
                "user_ref",
                "last_used_at",
                "prev_used_at",
                "last_observed_at",
                "hostname",
                "hostname_checked_at",
                "geo_status",
                "geo_next_attempt_at",
                "geo_checked_at",
                "geo_provider",
                "token_type",
                "username",
            ):
                if field in value:
                    summary[field] = value.get(field)
            summary["latest_was_new_ip"] = bool(value.get("latest_was_new_ip"))
            try:
                summary["geo_attempts"] = max(0, int(value.get("geo_attempts", 0)))
            except (TypeError, ValueError):
                summary["geo_attempts"] = 0
            if summary.get("username") is not None:
                summary["username"] = _text(summary.get("username"), 128)
            summary["hostname"] = _text(summary.get("hostname"), 253)
            summary["ip_scope"] = scope
            if scope != "public":
                summary["geo_status"] = "skipped"
            state["ip_summaries"][ip] = summary
    events = document.get("events")
    if isinstance(events, list):
        for item in events:
            if isinstance(item, dict) and isinstance(item.get("event_id"), str):
                state["events"].append(_sanitize_event(item))
    pending = document.get("pending_notifications")
    if isinstance(pending, list):
        for item in pending:
            if isinstance(item, dict) and isinstance(item.get("event_id"), str):
                state["pending_notifications"].append(
                    {
                        "event_id": item["event_id"][:64],
                        "ip_address": _text(item.get("ip_address"), 64),
                        "user_ref": _text(item.get("user_ref"), 64),
                        "reason": _text(item.get("reason"), 64),
                        "last_used_at": _text(item.get("last_used_at"), 64),
                    }
                )
    state["updated_at"] = isoformat(now)
    return state


def _sanitize_event(item: dict) -> dict:
    event = {
        "event_id": item["event_id"][:64],
        "observed_at": _text(item.get("observed_at"), 64),
        "token_ref": _text(item.get("token_ref"), 64),
        "user_ref": _text(item.get("user_ref"), 64),
        "ip_address": _text(item.get("ip_address"), 64),
        "ip_scope": _text(item.get("ip_scope"), 32),
        "last_used_at": _text(item.get("last_used_at"), 64),
        "token_type": _text(item.get("token_type"), 64),
        "observation_type": "token_use",
        "reason": _text(item.get("reason"), 64),
    }
    if "username" in item:
        event["username"] = _text(item.get("username"), 128)
    event.update(geo_from_mapping(item))
    return event


def strip_stored_usernames(state: dict) -> None:
    """Remove usernames from the active history document."""
    for summary in state.get("ip_summaries", {}).values():
        if isinstance(summary, dict):
            summary.pop("username", None)
    for event in state.get("events", []):
        if isinstance(event, dict):
            event.pop("username", None)


def retain_state(
    state: dict,
    *,
    now: datetime,
    retention_days: int,
    max_events: int,
    active_ips: set[str],
) -> None:
    """Drop expired events and summaries that are no longer referenced."""
    cutoff = now - timedelta(days=retention_days)
    kept = []
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        observed = parse_time(event.get("observed_at"))
        if observed is None or observed < cutoff:
            continue
        kept.append(event)
    kept.sort(key=lambda item: item.get("observed_at") or "")
    if len(kept) > max_events:
        kept = kept[-max_events:]
    state["events"] = kept
    referenced = {event.get("ip_address") for event in kept}
    referenced.update(active_ips)
    for ip, summary in list(state.get("ip_summaries", {}).items()):
        if ip in referenced:
            continue
        last_used = parse_time(summary.get("last_used_at")) if isinstance(summary, dict) else None
        if last_used is None or last_used < cutoff:
            del state["ip_summaries"][ip]
    live_ids = {event.get("event_id") for event in kept}
    state["pending_notifications"] = [
        item
        for item in state.get("pending_notifications", [])
        if isinstance(item, dict) and item.get("event_id") in live_ids
    ]
    state["updated_at"] = isoformat(now)
