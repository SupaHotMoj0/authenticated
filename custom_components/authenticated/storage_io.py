"""Local file IO for history. Auth storage is opened read-only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import stat
import tempfile

import yaml

from .history import (
    classify_document,
    empty_state,
    migrate_legacy,
    sanitize_v2,
)


@dataclass(frozen=True)
class JsonRead:
    """Read result whose error code never includes file contents."""

    document: dict | None
    error: str | None


@dataclass(frozen=True)
class HistoryLoad:
    """In-memory history and whether it may be written back."""

    state: dict | None
    writable: bool
    kind: str
    legacy_bytes: bytes | None = None


def read_json_readonly(path: str) -> JsonRead:
    """Read a JSON object without creating or modifying the file."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return JsonRead(None, "missing")
    except OSError:
        return JsonRead(None, "unreadable")
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            try:
                document = json.load(handle)
            except (json.JSONDecodeError, UnicodeError, ValueError):
                return JsonRead(None, "invalid_json")
    except OSError:
        return JsonRead(None, "unreadable")
    if not isinstance(document, dict):
        return JsonRead(None, "invalid_json")
    return JsonRead(document, None)


def _read_bytes(path: str) -> tuple[bytes | None, str]:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    try:
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read(), "ok"
    except OSError:
        return None, "unreadable"


def _write_private(path: str, payload: bytes) -> None:
    """Atomically replace ``path`` with a mode-0600 file."""
    directory = os.path.dirname(path) or "."
    descriptor, temporary = tempfile.mkstemp(
        dir=directory, prefix=".authenticated-", suffix=".tmp"
    )
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_backup_once(path: str, payload: bytes) -> bool:
    """Create a private backup if a regular backup file is not already there.

    An existing directory or other non-file is not treated as a backup, so the
    original history file is left in place.
    """
    if os.path.exists(path):
        return os.path.isfile(path) and os.path.getsize(path) > 0
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass
        return False


def dump_history(state: dict) -> bytes:
    """Serialize history with the safe YAML dumper."""
    text = yaml.safe_dump(
        state,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        explicit_start=True,
    )
    return text.encode("utf-8")


def write_history(path: str, state: dict) -> None:
    """Replace the history file atomically."""
    _write_private(path, dump_history(state))


def _load_yaml(payload: bytes) -> object:
    try:
        return yaml.safe_load(payload.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        return "invalid"


def upgrade_and_load(
    path: str,
    backup_path: str,
    now: datetime,
    *,
    store_usernames: bool,
) -> HistoryLoad:
    """Load history, backing up a legacy file before it can be replaced.

    A legacy document is migrated in memory. The caller writes version 2 only
    when ``writable`` is true. A failed backup leaves the original file in place.
    """
    payload, status = _read_bytes(path)
    if status == "missing":
        return HistoryLoad(empty_state(now), True, "missing")
    if status != "ok" or payload is None:
        return HistoryLoad(None, False, "unreadable")
    document = _load_yaml(payload)
    if document == "invalid":
        return HistoryLoad(None, False, "invalid")
    kind = classify_document(document)
    if kind == "missing":
        return HistoryLoad(empty_state(now), True, "missing")
    if kind == "invalid":
        return HistoryLoad(None, False, "invalid")
    if kind == "v2":
        return HistoryLoad(sanitize_v2(document, now), True, "v2")
    if not isinstance(document, dict):
        return HistoryLoad(None, False, "invalid")
    migrated = migrate_legacy(document, now, store_usernames=store_usernames)
    if not write_backup_once(backup_path, payload):
        return HistoryLoad(migrated, False, "legacy_backup_failed", payload)
    return HistoryLoad(migrated, True, "legacy", None)
