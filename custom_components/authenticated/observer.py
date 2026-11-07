"""Decide which token uses are new, which addresses need enrichment, and what to notify.

Polling Home Assistant's auth file can only see the latest ``last_used_at`` on each
refresh token. Two uses between polls collapse into the later timestamp. A change
proves the token was used, not that a person completed an interactive login.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .auth_source import TokenObservation
from .const import (
    GEO_BACKOFF_BASE_SECONDS,
    GEO_BACKOFF_CAP_SECONDS,
    GEO_MAX_ATTEMPTS,
    GEO_MAX_PER_POLL,
    GEO_NEGATIVE_TTL_SECONDS,
    GEO_SUCCESS_TTL_SECONDS,
    HOSTNAME_TTL_SECONDS,
    NOTIFY_ON_EVERY,
    OBSERVATION_TOKEN_USE,
    PROVIDER_COOLDOWN_SECONDS,
)
from .history import blank_summary, geo_from_mapping, retain_state
from .ip_util import address_excluded, classify_ip
from .providers import GeoResult
from .settings import Settings
from .time_util import event_id, isoformat, parse_time, same_instant


def backoff_seconds(attempts: int, *, jitter_seed: int = 0) -> int:
    """Exponential delay capped so a failure cannot spin."""
    exponent = min(max(attempts - 1, 0), 8)
    delay = min(GEO_BACKOFF_BASE_SECONDS * (2**exponent), GEO_BACKOFF_CAP_SECONDS)
    if jitter_seed:
        delay += jitter_seed % 30
    return int(delay)


def _jitter(ip: str) -> int:
    return sum(ip.encode("utf-8")) or 1


def _asn_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().upper()
    if text.startswith("AS"):
        text = text[2:]
    return text


def _excluded_by_policy(summary: dict, settings: Settings) -> bool:
    asn = _asn_key(summary.get("asn"))
    if asn and any(_asn_key(item) == asn for item in settings.notify_exclude_asn):
        return True
    hostname = summary.get("hostname")
    if isinstance(hostname, str):
        folded = hostname.casefold()
        if any(item.casefold() == folded for item in settings.notify_exclude_hostnames):
            return True
    return False


def filter_observations(
    observations: tuple[TokenObservation, ...] | list[TokenObservation],
    settings: Settings,
) -> list[TokenObservation]:
    """Drop excluded addresses and client ids. The client id is not returned."""
    selected = []
    for observation in observations:
        if address_excluded(observation.ip, list(settings.exclude)):
            continue
        if observation.client_id and observation.client_id in settings.exclude_clients:
            continue
        selected.append(observation)
    return selected


def _cursor_matches(cursor: dict | None, observation: TokenObservation) -> bool:
    if not cursor:
        return False
    return cursor.get("ip") == observation.ip and same_instant(
        cursor.get("last_used_at"), observation.last_used_at
    )


def _summary_covers(summary: dict | None, observation: TokenObservation) -> bool:
    """True when an existing summary already accounts for this token use.

    A summary with no comparable timestamp is treated as already known so the
    first poll after an upgrade does not notify for every stored address.
    """
    if not summary:
        return False
    last_used = parse_time(summary.get("last_used_at"))
    if last_used is None:
        return True
    return last_used >= observation.last_used_dt


def _apply_summary(
    summary: dict,
    observation: TokenObservation,
    *,
    now: datetime,
    is_new_ip: bool,
    store_username: bool,
) -> None:
    previous = summary.get("last_used_at")
    if previous and not same_instant(previous, observation.last_used_at):
        summary["prev_used_at"] = previous
    summary["last_used_at"] = observation.last_used_at
    summary["last_observed_at"] = isoformat(now)
    summary["user_ref"] = observation.user_ref
    summary["token_type"] = observation.token_type
    summary["ip_scope"] = observation.scope
    summary["latest_was_new_ip"] = is_new_ip
    if store_username and observation.username:
        summary["username"] = observation.username
    elif not store_username:
        summary.pop("username", None)
    if observation.scope != "public":
        summary["geo_status"] = "skipped"


def _make_event(
    observation: TokenObservation,
    summary: dict,
    *,
    now: datetime,
    reason: str,
    store_username: bool,
) -> dict:
    event = {
        "event_id": event_id(
            observation.token_ref, observation.last_used_at, observation.ip
        ),
        "observed_at": isoformat(now),
        "token_ref": observation.token_ref,
        "user_ref": observation.user_ref,
        "ip_address": observation.ip,
        "ip_scope": observation.scope,
        "last_used_at": observation.last_used_at,
        "token_type": observation.token_type,
        "observation_type": OBSERVATION_TOKEN_USE,
        "reason": reason,
    }
    if store_username and observation.username:
        event["username"] = observation.username
    event.update(geo_from_mapping(summary))
    return event


def ingest(
    state: dict,
    observations: list[TokenObservation],
    settings: Settings,
    now: datetime,
    *,
    auth_ok: bool,
    truncated: bool = False,
) -> None:
    """Update cursors and append events. Does not perform network IO."""
    if not auth_ok:
        return
    active_ips = {item.ip for item in observations}
    if not state.get("bootstrapped"):
        for observation in observations:
            summary = state["ip_summaries"].get(observation.ip)
            if summary is None:
                summary = blank_summary(observation.ip, observation.scope)
                state["ip_summaries"][observation.ip] = summary
            _apply_summary(
                summary,
                observation,
                now=now,
                is_new_ip=False,
                store_username=settings.store_usernames,
            )
            state["tokens"][observation.token_ref] = {
                "last_used_at": observation.last_used_at,
                "ip": observation.ip,
            }
        state["bootstrapped"] = True
        retain_state(
            state,
            now=now,
            retention_days=settings.retention_days,
            max_events=settings.max_events,
            active_ips=active_ips,
        )
        return

    seen: set[str] = set()
    for observation in observations:
        seen.add(observation.token_ref)
        cursor = state["tokens"].get(observation.token_ref)
        summary = state["ip_summaries"].get(observation.ip)
        if _cursor_matches(cursor, observation):
            continue
        if cursor is None and summary is not None and _summary_covers(summary, observation):
            _apply_summary(
                summary,
                observation,
                now=now,
                is_new_ip=False,
                store_username=settings.store_usernames,
            )
            state["tokens"][observation.token_ref] = {
                "last_used_at": observation.last_used_at,
                "ip": observation.ip,
            }
            continue
        is_new_ip = summary is None
        user_changed = bool(
            summary
            and summary.get("user_ref")
            and observation.user_ref
            and summary.get("user_ref") != observation.user_ref
        )
        if summary is None:
            summary = blank_summary(observation.ip, observation.scope)
            state["ip_summaries"][observation.ip] = summary
        reason = "new_ip" if is_new_ip else "user_changed" if user_changed else "token_use"
        event = _make_event(
            observation,
            summary,
            now=now,
            reason=reason,
            store_username=settings.store_usernames,
        )
        appended = not any(
            item.get("event_id") == event["event_id"] for item in state["events"]
        )
        if appended:
            state["events"].append(event)
        _apply_summary(
            summary,
            observation,
            now=now,
            is_new_ip=is_new_ip,
            store_username=settings.store_usernames,
        )
        state["tokens"][observation.token_ref] = {
            "last_used_at": observation.last_used_at,
            "ip": observation.ip,
        }
        if appended:
            _queue_notification(state, settings, event)

    if not truncated:
        state["tokens"] = {
            key: value for key, value in state["tokens"].items() if key in seen
        }
    retain_state(
        state,
        now=now,
        retention_days=settings.retention_days,
        max_events=settings.max_events,
        active_ips=active_ips,
    )


def _notifications_enabled(settings: Settings) -> bool:
    return bool(settings.notify or settings.notify_services)


def _queue_notification(state: dict, settings: Settings, event: dict) -> None:
    if not _notifications_enabled(settings):
        return
    reason = event.get("reason")
    if settings.notify_on != NOTIFY_ON_EVERY and reason not in {"new_ip", "user_changed"}:
        return
    item = {
        "event_id": event["event_id"],
        "ip_address": event["ip_address"],
        "user_ref": event.get("user_ref"),
        "reason": reason,
        "last_used_at": event.get("last_used_at"),
    }
    if any(
        existing.get("event_id") == item["event_id"]
        for existing in state["pending_notifications"]
    ):
        return
    state["pending_notifications"].append(item)


def geo_due(summary: dict, now: datetime, cooldown_until: datetime | None) -> bool:
    """Return True when one enrichment attempt is allowed."""
    if summary.get("ip_scope") != "public":
        return False
    status = summary.get("geo_status")
    if status == "skipped":
        return False
    if status == "complete":
        checked = parse_time(summary.get("geo_checked_at"))
        if checked is not None and (now - checked).total_seconds() < GEO_SUCCESS_TTL_SECONDS:
            return False
    next_attempt = parse_time(summary.get("geo_next_attempt_at"))
    if next_attempt is not None and now < next_attempt:
        return False
    if cooldown_until is not None and now < cooldown_until:
        return False
    return True


def select_geo_targets(state: dict, settings: Settings, now: datetime) -> list[str]:
    """Choose a bounded set of public addresses whose geo data is due."""
    if not settings.enrich_public_ips:
        return []
    cooldown = parse_time(state.get("provider_cooldown_until"))
    pending_ips = []
    for item in state.get("pending_notifications", []):
        ip = item.get("ip_address")
        if isinstance(ip, str) and ip not in pending_ips:
            pending_ips.append(ip)
    ordered = pending_ips + [
        ip for ip in state.get("ip_summaries", {}) if ip not in pending_ips
    ]
    targets: list[str] = []
    for ip in ordered:
        summary = state["ip_summaries"].get(ip)
        if not isinstance(summary, dict):
            continue
        scope = classify_ip(ip)
        summary["ip_scope"] = scope
        if scope != "public":
            summary["geo_status"] = "skipped"
            continue
        if geo_due(summary, now, cooldown):
            targets.append(ip)
        if len(targets) >= GEO_MAX_PER_POLL:
            break
    return targets


def apply_geo_result(
    state: dict,
    ip: str,
    result: GeoResult,
    *,
    provider: str,
    now: datetime,
) -> None:
    """Record one attempt. A later failure does not erase a complete result."""
    summary = state["ip_summaries"].get(ip)
    if not isinstance(summary, dict):
        return
    if classify_ip(ip) != "public":
        summary["geo_status"] = "skipped"
        return
    summary["geo_provider"] = provider
    if result.status == "skipped":
        summary["geo_status"] = "skipped"
        summary["geo_attempts"] = 0
        summary["geo_next_attempt_at"] = None
        summary["geo_checked_at"] = isoformat(now)
        return
    if result.status == "complete":
        summary.update(result.fields)
        summary["geo_status"] = "complete"
        summary["geo_attempts"] = 0
        summary["geo_next_attempt_at"] = None
        summary["geo_checked_at"] = isoformat(now)
        _copy_geo_to_latest_event(state, ip, summary)
        return
    schedule_retry(state, summary, result, now, jitter_seed=_jitter(ip))


def schedule_retry(
    state: dict,
    summary: dict,
    result: GeoResult,
    now: datetime,
    *,
    jitter_seed: int = 0,
) -> None:
    """Record a bounded backoff. The fourth failure waits a full day."""
    attempts = int(summary.get("geo_attempts") or 0) + 1
    summary["geo_status"] = (
        result.status if result.status in {"rate_limited", "incomplete", "error"} else "error"
    )
    delay = backoff_seconds(attempts, jitter_seed=jitter_seed)
    if result.retry_after:
        delay = max(delay, int(result.retry_after))
    if result.status == "rate_limited":
        delay = max(delay, PROVIDER_COOLDOWN_SECONDS)
        state["provider_cooldown_until"] = isoformat(
            now + timedelta(seconds=max(delay, PROVIDER_COOLDOWN_SECONDS))
        )
    if attempts >= GEO_MAX_ATTEMPTS:
        summary["geo_attempts"] = 0
        summary["geo_next_attempt_at"] = isoformat(
            now + timedelta(seconds=GEO_NEGATIVE_TTL_SECONDS)
        )
    else:
        summary["geo_attempts"] = attempts
        summary["geo_next_attempt_at"] = isoformat(now + timedelta(seconds=delay))
    summary["geo_checked_at"] = isoformat(now)


def _copy_geo_to_latest_event(state: dict, ip: str, summary: dict) -> None:
    for event in reversed(state.get("events", [])):
        if event.get("ip_address") == ip:
            event.update(geo_from_mapping(summary))
            return


def _defer_for_asn(summary: dict, settings: Settings, now: datetime) -> bool:
    if not settings.notify_exclude_asn or not settings.enrich_public_ips:
        return False
    if summary.get("ip_scope") != "public":
        return False
    if summary.get("geo_status") in {"complete", "skipped"}:
        return False
    cooldown = None
    return geo_due(summary, now, cooldown)


def collect_notifications(
    state: dict,
    settings: Settings,
    names: dict[str, str | None],
    now: datetime,
) -> list[dict]:
    """Return payloads whose exclusions can be applied, and drop the rest from the queue."""
    if not _notifications_enabled(settings):
        state["pending_notifications"] = []
        return []
    ready: list[dict] = []
    waiting: list[dict] = []
    for item in list(state.get("pending_notifications", [])):
        ip = item.get("ip_address")
        summary = state["ip_summaries"].get(ip, {})
        if not isinstance(summary, dict):
            summary = {}
        if _defer_for_asn(summary, settings, now):
            waiting.append(item)
            continue
        if _excluded_by_policy(summary, settings):
            continue
        ready.append(_payload(item, summary, names, settings))
    state["pending_notifications"] = waiting
    return ready


def _payload(item: dict, summary: dict, names: dict[str, str | None], settings: Settings) -> dict:
    username = None
    user_reference = item.get("user_ref")
    if isinstance(user_reference, str):
        username = names.get(user_reference)
    if settings.store_usernames and not username:
        username = summary.get("username")
    title = "New IP observed" if item.get("reason") == "new_ip" else "Token use observed"
    lines = [
        "Home Assistant recorded a refresh-token use.",
        "This is not proof of an interactive login.",
        f"IP address: {item.get('ip_address')}",
        f"Address type: {summary.get('ip_scope') or 'unknown'}",
    ]
    if username:
        lines.append(f"User: {username}")
    if item.get("last_used_at"):
        lines.append(f"Token last used: {item['last_used_at']}")
    for field, label in (
        ("country", "Country"),
        ("country_code", "Country code"),
        ("region", "Region"),
        ("city", "City"),
        ("asn", "ASN"),
        ("org", "Organisation"),
        ("timezone", "Timezone"),
        ("hostname", "Hostname"),
    ):
        value = summary.get(field)
        if value:
            lines.append(f"{label}: {value}")
    message = "\n".join(lines)[:2000]
    return {
        "title": title,
        "message": message,
        "services": list(settings.notify_services),
        "persistent": settings.notify,
        "notification_id": f"authenticated_{item.get('event_id')}",
    }


def build_snapshot(
    observations: list[TokenObservation],
    state: dict,
) -> dict | None:
    """Build the sensor view from the latest auth read. It is not written to disk."""
    if not observations:
        return None
    latest = max(observations, key=lambda item: item.last_used_dt)
    summary = state["ip_summaries"].get(latest.ip, {})
    if not isinstance(summary, dict):
        summary = {}
    snapshot = {
        "ip_address": latest.ip,
        "ip_scope": latest.scope,
        "username": latest.username or "Unknown",
        "hostname": summary.get("hostname"),
        "new_ip": bool(summary.get("latest_was_new_ip")),
        "last_used_at": latest.last_used_at,
        "prev_used_at": summary.get("prev_used_at"),
        "last_observed_at": summary.get("last_observed_at"),
        "token_type": latest.token_type,
        "geo_status": summary.get("geo_status"),
        "geo_provider": summary.get("geo_provider"),
        "history_count": len(state.get("events", [])),
        "observation_type": OBSERVATION_TOKEN_USE,
    }
    snapshot.update(geo_from_mapping(summary))
    return snapshot


def hostname_due(summary: dict, settings: Settings, now: datetime) -> bool:
    """Reverse DNS is opt-in and is not repeated on every poll."""
    if not settings.resolve_hostnames:
        return False
    if summary.get("ip_scope") != "public":
        return False
    checked = parse_time(summary.get("hostname_checked_at"))
    if checked is not None and (now - checked).total_seconds() < HOSTNAME_TTL_SECONDS:
        return False
    return True
