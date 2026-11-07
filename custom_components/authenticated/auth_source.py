"""Read-only interpretation of a Home Assistant auth storage document.

The on-disk file is ``.storage/auth``. Home Assistant Core 2026.11 writes
``last_used_at`` and ``last_used_ip`` when a refresh token is exchanged for an
access token. That is token use, not a separate login record. This module never
writes and never copies token secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .const import TOKEN_OBSERVATION_CAP
from .ip_util import canonical_ip, classify_ip
from .time_util import parse_time, token_ref, user_ref

# Only these refresh-token fields are read. Token secrets are not in the list.
TOKEN_FIELDS = (
    "id",
    "user_id",
    "client_id",
    "token_type",
    "last_used_at",
    "last_used_ip",
)


@dataclass(frozen=True)
class TokenObservation:
    """One refresh token's latest stored use, with secrets already removed."""

    token_ref: str
    user_ref: str | None
    username: str | None
    ip: str
    scope: str
    last_used_at: str
    last_used_dt: datetime
    token_type: str
    client_id: str | None


@dataclass(frozen=True)
class AuthParse:
    """Result of reading an auth document. ``error`` is a short code, never a payload."""

    observations: tuple[TokenObservation, ...]
    error: str | None = None
    skipped: int = 0
    truncated: bool = False


def _data_section(document: object) -> dict | None:
    if not isinstance(document, dict):
        return None
    data = document.get("data") if "data" in document else document
    if not isinstance(data, dict):
        return None
    return data


def _clean_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:128]


def _token_type(value: object) -> str:
    if value in ("normal", "system", "long_lived_access_token"):
        return value
    return "unknown"


def parse_auth_document(document: object) -> AuthParse:
    """Extract token-use observations. Malformed tokens are skipped."""
    data = _data_section(document)
    if data is None:
        return AuthParse((), error="unrecognized")
    users_raw = data.get("users", [])
    tokens_raw = data.get("refresh_tokens", [])
    if not isinstance(users_raw, list) or not isinstance(tokens_raw, list):
        return AuthParse((), error="unrecognized")

    names: dict[str, str | None] = {}
    for user in users_raw:
        if not isinstance(user, dict):
            continue
        user_id = user.get("id")
        if isinstance(user_id, str) and user_id:
            names[user_id] = _clean_name(user.get("name"))

    parsed: list[TokenObservation] = []
    skipped = 0
    for token in tokens_raw:
        if not isinstance(token, dict):
            skipped += 1
            continue
        selected = {key: token.get(key) for key in TOKEN_FIELDS}
        token_id = selected.get("id")
        ip_raw = selected.get("last_used_ip")
        used_raw = selected.get("last_used_at")
        if not isinstance(token_id, str) or not token_id:
            skipped += 1
            continue
        if not isinstance(ip_raw, str) or not isinstance(used_raw, str):
            skipped += 1
            continue
        ip = canonical_ip(ip_raw)
        used_dt = parse_time(used_raw)
        if ip is None or used_dt is None:
            skipped += 1
            continue
        user_id = selected.get("user_id")
        user_reference = None
        username = None
        if isinstance(user_id, str) and user_id:
            user_reference = user_ref(user_id)
            username = names.get(user_id)
        client_id = selected.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            client_id = None
        parsed.append(
            TokenObservation(
                token_ref=token_ref(token_id),
                user_ref=user_reference,
                username=username,
                ip=ip,
                scope=classify_ip(ip),
                last_used_at=used_raw,
                last_used_dt=used_dt,
                token_type=_token_type(selected.get("token_type")),
                client_id=client_id,
            )
        )

    parsed.sort(key=lambda item: item.last_used_dt, reverse=True)
    truncated = False
    if len(parsed) > TOKEN_OBSERVATION_CAP:
        skipped += len(parsed) - TOKEN_OBSERVATION_CAP
        parsed = parsed[:TOKEN_OBSERVATION_CAP]
        truncated = True
    return AuthParse(tuple(parsed), skipped=skipped, truncated=truncated)
