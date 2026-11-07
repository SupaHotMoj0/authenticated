"""Small time and identifier helpers with no Home Assistant import."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    """Serialize UTC time with second precision."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive values are treated as UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def same_instant(left: object, right: object) -> bool:
    """Compare two timestamps by instant when both parse."""
    parsed_left = parse_time(left)
    parsed_right = parse_time(right)
    if parsed_left is not None and parsed_right is not None:
        return parsed_left == parsed_right
    return left == right


def digest(value: str) -> str:
    """Stable short reference. Not a secret and not reversible."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def user_ref(user_id: str) -> str:
    """Opaque reference for a Home Assistant user id."""
    return digest("user:" + user_id)


def token_ref(token_id: str) -> str:
    """Opaque reference for a refresh-token id. The token secret is never hashed."""
    return digest("token-id:" + token_id)


def event_id(token_reference: str, last_used_at: str, ip: str) -> str:
    """Idempotent id for one observed token-use instant."""
    return digest(f"event:{token_reference}|{last_used_at}|{ip}")
