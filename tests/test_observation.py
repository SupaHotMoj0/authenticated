"""Regression tests for token-use observation, enrichment, and history.

These tests use documentation and private addresses only. They do not open a
socket. They do not boot Home Assistant.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import stat

import aiohttp
import pytest
import yaml

from custom_components.authenticated.auth_source import parse_auth_document
from custom_components.authenticated.const import AUTH_SECRET_KEYS, GEO_NEGATIVE_TTL_SECONDS
from custom_components.authenticated.history import empty_state, strip_stored_usernames
from custom_components.authenticated.ip_util import classify_ip, safe_config_relative
from custom_components.authenticated.lifecycle import Lifecycle
from custom_components.authenticated.notify import async_dispatch
from custom_components.authenticated.observer import (
    apply_geo_result,
    build_snapshot,
    collect_notifications,
    filter_observations,
    geo_due,
    hostname_due,
    ingest,
    schedule_retry,
    select_geo_targets,
)
from custom_components.authenticated.providers import (
    IPInfo,
    async_lookup_ip,
    build_url,
    create_session,
    interpret_response,
    read_http,
)
from custom_components.authenticated.settings import SettingsError, settings_from_mapping, storage_from_form
from custom_components.authenticated.storage_io import (
    read_json_readonly,
    upgrade_and_load,
    write_history,
)
from custom_components.authenticated.time_util import token_ref

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
EARLIER = "2026-11-07T11:00:00+00:00"
LATER = "2026-11-07T11:30:00+00:00"
DOC = "203.0.113.10"
DOC_2 = "198.51.100.20"
PRIVATE = "10.0.0.8"
TOKEN_SENTINEL = "TEST_REFRESH_TOKEN_SENTINEL"
JWT_SENTINEL = "TEST_JWT_KEY_SENTINEL"
PASSWORD_SENTINEL = "TEST_PASSWORD_SENTINEL"
USER_ID = "user-example-1"
USERNAME = "person-example"
CLIENT = "https://example.invalid/app"


def _settings(**overrides):
    mapping = {
        "enable_notification": True,
        "notify_services": ["notify.mobile_app_example"],
        "notify_on": "new_ip",
        "enrich_public_ips": True,
        "store_usernames": False,
        "resolve_hostnames": False,
    }
    mapping.update(overrides)
    return settings_from_mapping(mapping)


def _token(token_id, ip, used, user_id=USER_ID, client=CLIENT, token_type="normal"):
    return {
        "id": token_id,
        "user_id": user_id,
        "client_id": client,
        "token_type": token_type,
        "last_used_at": used,
        "last_used_ip": ip,
        "token": TOKEN_SENTINEL,
        "jwt_key": JWT_SENTINEL,
    }


def _document(tokens):
    return {
        "version": 1,
        "minor_version": 1,
        "key": "auth",
        "data": {
            "users": [{"id": USER_ID, "name": USERNAME}, {"id": "user-example-2", "name": "other-example"}],
            "groups": [],
            "credentials": [{"data": {"password": PASSWORD_SENTINEL}}],
            "refresh_tokens": tokens,
        },
    }


def _observations(tokens):
    parsed = parse_auth_document(_document(tokens))
    assert parsed.error is None
    return parsed


def _state_text(state) -> str:
    return json.dumps(state)


def test_special_ranges_are_not_public():
    samples = {
        "203.0.113.10": "documentation",
        "198.51.100.5": "documentation",
        "192.0.2.1": "documentation",
        "2001:db8::1": "documentation",
        "10.1.2.3": "private",
        "192.168.1.10": "private",
        "fd00::1": "private",
        "127.0.0.1": "loopback",
        "::1": "loopback",
        "169.254.1.1": "link_local",
        "fe80::1": "link_local",
        "100.64.1.1": "shared",
        "0.0.0.0": "unspecified",
        "224.0.0.1": "multicast",
        "255.255.255.255": "reserved",
        "not-an-ip": "invalid",
    }
    assert all(classify_ip(ip) == scope for ip, scope in samples.items())
    assert all(classify_ip(ip) != "public" for ip in samples)


def test_auth_parse_keeps_secrets_and_headers_out():
    parsed = _observations([_token("token-example-1", DOC, EARLIER)])
    observation = parsed.observations[0]
    blob = repr(observation)
    assert TOKEN_SENTINEL not in blob
    assert JWT_SENTINEL not in blob
    assert PASSWORD_SENTINEL not in blob
    assert observation.token_ref == token_ref("token-example-1")
    assert "token-example-1" not in observation.token_ref
    assert observation.username == USERNAME
    assert observation.scope == "documentation"
    assert observation.client_id == CLIENT
    assert AUTH_SECRET_KEYS.isdisjoint(
        {
            "id",
            "user_id",
            "client_id",
            "token_type",
            "last_used_at",
            "last_used_ip",
        }
    )


def test_only_latest_stored_use_is_visible():
    """Auth storage has one last-use pair per token, so an earlier use is gone."""
    parsed = _observations([_token("token-example-1", DOC, LATER)])
    assert len(parsed.observations) == 1
    assert parsed.observations[0].last_used_at == LATER


def test_missing_last_use_is_skipped_without_dropping_the_file():
    parsed = _observations(
        [
            _token("token-example-1", DOC, EARLIER),
            {"id": "token-example-2", "token": TOKEN_SENTINEL, "jwt_key": JWT_SENTINEL},
        ]
    )
    assert len(parsed.observations) == 1
    assert parsed.skipped == 1


def test_reader_does_not_create_or_modify_auth_file(tmp_path):
    target = tmp_path / "auth"
    payload = json.dumps(_document([_token("token-example-1", DOC, EARLIER)])).encode()
    target.write_bytes(payload)
    before = target.stat().st_mtime_ns
    mode = target.stat().st_mode
    result = read_json_readonly(str(target))
    assert result.error is None
    assert target.read_bytes() == payload
    assert target.stat().st_mtime_ns == before
    assert target.stat().st_mode == mode
    missing = tmp_path / "missing-auth"
    assert read_json_readonly(str(missing)).error == "missing"
    assert not missing.exists()


def test_invalid_auth_json_does_not_echo_the_body(tmp_path):
    target = tmp_path / "auth"
    target.write_text('{"token": "' + TOKEN_SENTINEL + '"', encoding="utf-8")
    result = read_json_readonly(str(target))
    assert result.error == "invalid_json"
    assert result.document is None
    assert TOKEN_SENTINEL not in (result.error or "")


def test_bootstrap_does_not_notify_and_later_uses_are_kept():
    settings = _settings()
    state = empty_state(NOW)
    first = filter_observations(
        _observations([_token("token-example-1", DOC, EARLIER)]).observations,
        settings,
    )
    ingest(state, first, settings, NOW, auth_ok=True)
    assert state["bootstrapped"] is True
    assert state["events"] == []
    assert state["pending_notifications"] == []
    assert DOC in state["ip_summaries"]

    second = filter_observations(
        _observations(
            [
                _token("token-example-1", DOC, LATER),
                _token("token-example-2", DOC_2, LATER),
            ]
        ).observations,
        settings,
    )
    ingest(state, second, settings, NOW + timedelta(minutes=1), auth_ok=True)
    assert len(state["events"]) == 2
    assert {event["ip_address"] for event in state["events"]} == {DOC, DOC_2}
    assert all(event["observation_type"] == "token_use" for event in state["events"])
    blob = _state_text(state)
    assert USERNAME not in blob
    assert USER_ID not in blob
    assert CLIENT not in blob
    assert TOKEN_SENTINEL not in blob

    ingest(state, second, settings, NOW + timedelta(minutes=2), auth_ok=True)
    assert len(state["events"]) == 2


def test_same_address_refresh_does_not_notify_unless_requested():
    settings = _settings(notify_on="new_ip")
    state = empty_state(NOW)
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, EARLIER)]).observations, settings),
        settings,
        NOW,
        auth_ok=True,
    )
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, LATER)]).observations, settings),
        settings,
        NOW + timedelta(minutes=1),
        auth_ok=True,
    )
    assert len(state["events"]) == 1
    assert state["pending_notifications"] == []

    noisy = _settings(notify_on="every_observation")
    state = empty_state(NOW)
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, EARLIER)]).observations, noisy),
        noisy,
        NOW,
        auth_ok=True,
    )
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, LATER)]).observations, noisy),
        noisy,
        NOW + timedelta(minutes=1),
        auth_ok=True,
    )
    assert len(state["pending_notifications"]) == 1


def test_user_change_on_known_address_is_notified():
    settings = _settings()
    state = empty_state(NOW)
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, EARLIER)]).observations, settings),
        settings,
        NOW,
        auth_ok=True,
    )
    changed = _token("token-example-1", DOC, LATER, user_id="user-example-2")
    ingest(
        state,
        filter_observations(_observations([changed]).observations, settings),
        settings,
        NOW + timedelta(minutes=1),
        auth_ok=True,
    )
    assert state["pending_notifications"][0]["reason"] == "user_changed"


def test_private_and_excluded_addresses_are_not_enriched():
    settings = _settings(exclude="203.0.113.0/24")
    state = empty_state(NOW)
    observations = filter_observations(
        _observations(
            [
                _token("token-example-1", DOC, EARLIER),
                _token("token-example-2", PRIVATE, EARLIER, client="https://example.invalid/other"),
            ]
        ).observations,
        settings,
    )
    assert [item.ip for item in observations] == [PRIVATE]
    ingest(state, observations, settings, NOW, auth_ok=True)
    assert select_geo_targets(state, settings, NOW) == []
    assert state["ip_summaries"][PRIVATE]["geo_status"] == "skipped"
    assert hostname_due(state["ip_summaries"][PRIVATE], settings, NOW) is False


def test_documentation_address_is_never_a_geo_target_even_when_incomplete():
    settings = _settings()
    state = empty_state(NOW)
    state["bootstrapped"] = True
    state["ip_summaries"][DOC] = {
        "ip_address": DOC,
        "ip_scope": "public",
        "geo_status": "incomplete",
        "geo_attempts": 0,
        "geo_next_attempt_at": None,
        "geo_checked_at": None,
    }
    assert select_geo_targets(state, settings, NOW) == []
    assert state["ip_summaries"][DOC]["geo_status"] == "skipped"
    disabled = _settings(enrich_public_ips=False)
    summary = {"ip_scope": "public", "geo_status": "incomplete", "geo_attempts": 0}
    state["ip_summaries"]["203.0.113.11"] = dict(summary)
    assert select_geo_targets(state, disabled, NOW) == []


def test_incomplete_lookup_backs_off_and_then_waits_a_day():
    state = {"provider_cooldown_until": None}
    summary = {"ip_scope": "public", "geo_status": "incomplete", "geo_attempts": 0, "geo_next_attempt_at": None}
    assert geo_due(summary, NOW, None) is True
    schedule_retry(state, summary, type("R", (), {"status": "error", "retry_after": None})(), NOW, jitter_seed=0)
    assert summary["geo_attempts"] == 1
    assert geo_due(summary, NOW + timedelta(seconds=30), None) is False
    assert geo_due(summary, NOW + timedelta(seconds=61), None) is True
    summary["geo_attempts"] = 3
    schedule_retry(state, summary, type("R", (), {"status": "error", "retry_after": None})(), NOW, jitter_seed=0)
    assert summary["geo_attempts"] == 0
    nxt = datetime.fromisoformat(summary["geo_next_attempt_at"])
    assert nxt - NOW == timedelta(seconds=GEO_NEGATIVE_TTL_SECONDS)
    assert geo_due(summary, NOW + timedelta(hours=1), None) is False


def test_rate_limit_sets_a_provider_cooldown():
    state = {"provider_cooldown_until": None}
    summary = {"geo_attempts": 0, "geo_status": "incomplete"}
    result = type("R", (), {"status": "rate_limited", "retry_after": 30})()
    schedule_retry(state, summary, result, NOW, jitter_seed=0)
    cooldown = datetime.fromisoformat(state["provider_cooldown_until"])
    assert cooldown >= NOW + timedelta(seconds=15 * 60)
    assert geo_due({"ip_scope": "public", "geo_status": "incomplete"}, NOW, cooldown) is False


def test_complete_geo_is_stored_for_a_public_result(monkeypatch):
    import custom_components.authenticated.observer as observer

    monkeypatch.setattr(observer, "classify_ip", lambda _ip: "public")
    state = empty_state(NOW)
    state["ip_summaries"][DOC] = {
        "ip_address": DOC,
        "ip_scope": "public",
        "geo_status": "incomplete",
        "geo_attempts": 2,
        "city": "Old Example",
    }
    state["events"] = [{"event_id": "evt", "ip_address": DOC, "city": None}]
    apply_geo_result(
        state,
        DOC,
        type(
            "R",
            (),
            {
                "status": "complete",
                "fields": {"city": "Example City", "country_code": "EX", "asn": "AS64500"},
                "retry_after": None,
            },
        )(),
        provider="ipapi",
        now=NOW,
    )
    summary = state["ip_summaries"][DOC]
    assert summary["geo_status"] == "complete"
    assert summary["city"] == "Example City"
    assert summary["geo_attempts"] == 0
    assert state["events"][0]["asn"] == "AS64500"
    schedule_retry(
        state,
        summary,
        type("R", (), {"status": "error", "retry_after": None})(),
        NOW,
        jitter_seed=0,
    )
    assert summary["city"] == "Example City"


def test_complete_result_is_cached_and_failure_does_not_erase_it():
    state = empty_state(NOW)
    state["ip_summaries"][DOC] = {
        "ip_address": DOC,
        "ip_scope": "documentation",
        "geo_status": "incomplete",
        "geo_attempts": 2,
    }
    state["events"] = [{"event_id": "evt", "ip_address": DOC}]
    apply_geo_result(
        state,
        DOC,
        type("R", (), {"status": "complete", "fields": {"city": "Example", "country": "Exampleland"}, "retry_after": None})(),
        provider="ipapi",
        now=NOW,
    )
    assert state["ip_summaries"][DOC]["geo_status"] == "skipped"
    summary = {
        "ip_scope": "public",
        "geo_status": "complete",
        "geo_checked_at": NOW.isoformat(),
        "city": "Example",
        "geo_attempts": 0,
        "geo_next_attempt_at": None,
    }
    assert geo_due(summary, NOW + timedelta(days=1), None) is False
    assert geo_due(summary, NOW + timedelta(days=8), None) is True


def test_history_retention_and_cap():
    settings = _settings(history_retention_days=30, history_max_events=10, enable_notification=False, notify_services=[])
    state = empty_state(NOW - timedelta(days=10))
    observations = []
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    tokens = []
    for index in range(12):
        used = (base + timedelta(days=index)).isoformat()
        tokens.append(_token(f"token-example-{index}", f"203.0.113.{index + 1}", used))
    parsed = _observations(tokens)
    ingest(state, filter_observations(parsed.observations, settings), settings, base, auth_ok=True)
    later = base + timedelta(days=40)
    refreshed = []
    for index, observation in enumerate(parsed.observations):
        used = (later + timedelta(minutes=index)).isoformat()
        refreshed.append(_token(f"token-example-{index}", observation.ip, used))
    ingest(
        state,
        filter_observations(_observations(refreshed).observations, settings),
        settings,
        later,
        auth_ok=True,
    )
    assert len(state["events"]) == 10
    assert all(
        datetime.fromisoformat(event["observed_at"]) >= later - timedelta(days=30)
        for event in state["events"]
    )


def test_legacy_migration_backs_up_and_strips_usernames(tmp_path):
    path = tmp_path / ".ip_authenticated.yaml"
    backup = tmp_path / ".ip_authenticated.yaml.v1.bak"
    legacy = {
        DOC: {
            "user_id": USER_ID,
            "username": USERNAME,
            "last_used_at": EARLIER,
            "country": None,
            "city": None,
            "token": TOKEN_SENTINEL,
        }
    }
    path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    original = path.read_bytes()
    loaded = upgrade_and_load(str(path), str(backup), NOW, store_usernames=False)
    assert loaded.kind == "legacy"
    assert loaded.writable is True
    assert backup.read_bytes() == original
    assert USERNAME in backup.read_text(encoding="utf-8")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    blob = _state_text(loaded.state)
    assert USERNAME not in blob
    assert USER_ID not in blob
    assert TOKEN_SENTINEL not in blob
    assert loaded.state["bootstrapped"] is True
    assert loaded.state["ip_summaries"][DOC]["geo_status"] == "skipped"
    write_history(str(path), loaded.state)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert USERNAME not in path.read_text(encoding="utf-8")
    assert path.read_bytes() != original
    again = upgrade_and_load(str(path), str(backup), NOW, store_usernames=False)
    assert again.kind == "v2"
    assert backup.read_bytes() == original


def test_corrupt_history_is_not_replaced(tmp_path):
    path = tmp_path / ".ip_authenticated.yaml"
    backup = tmp_path / ".ip_authenticated.yaml.v1.bak"
    path.write_text(":\n" + USERNAME, encoding="utf-8")
    original = path.read_bytes()
    loaded = upgrade_and_load(str(path), str(backup), NOW, store_usernames=False)
    assert loaded.writable is False
    assert loaded.state is None
    assert path.read_bytes() == original
    assert not backup.exists()


def test_upgrade_refuses_to_replace_without_backup(tmp_path):
    path = tmp_path / ".ip_authenticated.yaml"
    backup = tmp_path / ".ip_authenticated.yaml.v1.bak"
    path.write_text(yaml.safe_dump({DOC: {"last_used_at": EARLIER, "username": USERNAME}}), encoding="utf-8")
    backup.mkdir()
    loaded = upgrade_and_load(str(path), str(backup), NOW, store_usernames=False)
    assert loaded.kind == "legacy_backup_failed"
    assert loaded.writable is False
    assert loaded.legacy_bytes
    assert USERNAME in path.read_text(encoding="utf-8")


def test_disabling_usernames_strips_the_active_document():
    state = empty_state(NOW)
    state["ip_summaries"][DOC] = {"username": USERNAME}
    state["events"] = [{"event_id": "evt", "username": USERNAME}]
    strip_stored_usernames(state)
    assert "username" not in _state_text(state)


def test_failed_auth_read_does_not_prune_history():
    settings = _settings(enable_notification=False, notify_services=[])
    state = empty_state(NOW)
    ingest(
        state,
        filter_observations(_observations([_token("token-example-1", DOC, EARLIER)]).observations, settings),
        settings,
        NOW,
        auth_ok=True,
    )
    assert state["tokens"]
    ingest(state, [], settings, NOW, auth_ok=False)
    assert state["tokens"]


def test_snapshot_says_token_use_and_is_not_the_history_file():
    settings = _settings()
    state = empty_state(NOW)
    observations = filter_observations(
        _observations([_token("token-example-1", PRIVATE, EARLIER)]).observations, settings
    )
    ingest(state, observations, settings, NOW, auth_ok=True)
    snapshot = build_snapshot(observations, state)
    assert snapshot["ip_address"] == PRIVATE
    assert snapshot["observation_type"] == "token_use"
    assert snapshot["username"] == USERNAME
    assert "events" not in snapshot


def test_notify_service_validation_and_defaults():
    stored = storage_from_form(
        {
            "provider": "ipinfo",
            "notify_services": "notify.mobile_app_example, mobile_app_example",
            "exclude": "203.0.113.10, 198.51.100.0/24",
            "history_retention_days": 14,
            "history_max_events": 50,
        }
    )
    assert stored["notify_services"] == ["mobile_app_example"]
    assert stored["exclude"] == ["203.0.113.10/32", "198.51.100.0/24"]
    assert stored["store_usernames"] is False
    assert stored["resolve_hostnames"] is False
    assert stored["enrich_public_ips"] is True
    with pytest.raises(SettingsError) as raised:
        storage_from_form({"notify_services": "mobile app"})
    assert raised.value.key == "invalid_notify_service"
    with pytest.raises(SettingsError):
        storage_from_form({"exclude": "not-a-network"})
    with pytest.raises(SettingsError):
        storage_from_form({"notify_services": ", ".join(f"mobile_app_{index}" for index in range(9))})
    lenient = settings_from_mapping({"provider": "somewhere", "history_retention_days": 0})
    assert lenient.provider == "ipapi"
    assert lenient.retention_days == 30
    assert safe_config_relative(".storage/auth") is None
    assert safe_config_relative("/tmp/history.yaml") is None
    assert safe_config_relative("../history.yaml") is None
    assert safe_config_relative("authenticated-history.yaml") == "authenticated-history.yaml"


def test_notifications_are_isolated(caplog):
    async def persistent(_payload):
        raise RuntimeError(DOC)

    async def mobile(service, _payload):
        if service == "mobile_app_example":
            raise RuntimeError(DOC)
        return None

    payloads = [
        {
            "title": "Token use observed",
            "message": f"IP address: {DOC}",
            "persistent": True,
            "services": ["mobile_app_example", "mobile_app_other"],
            "notification_id": "authenticated_evt",
        }
    ]
    with caplog.at_level(logging.WARNING):
        outcomes = asyncio.run(
            async_dispatch(payloads, persistent=persistent, mobile=mobile, timeout=1)
        )
    assert outcomes == [
        "persistent:error",
        "mobile_app_example:error",
        "mobile_app_other:ok",
    ]
    assert DOC not in caplog.text


def test_asn_exclusion_drops_the_notification_after_geo():
    settings = _settings(notify_exclude_asns="AS64500")
    state = empty_state(NOW)
    state["bootstrapped"] = True
    state["ip_summaries"][DOC] = {
        "ip_address": DOC,
        "ip_scope": "documentation",
        "asn": "AS64500",
        "geo_status": "complete",
    }
    state["pending_notifications"] = [
        {
            "event_id": "evt",
            "ip_address": DOC,
            "user_ref": None,
            "reason": "new_ip",
            "last_used_at": EARLIER,
        }
    ]
    assert collect_notifications(state, settings, {}, NOW) == []
    assert state["pending_notifications"] == []


class _FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = self
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    async def read(self, _n=-1):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _FakeSession:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.urls = []
        self.kwargs = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def test_provider_guard_and_parsers(caplog):
    with pytest.raises(ValueError):
        build_url("ipapi", DOC)
    session = _FakeSession(error=AssertionError("network"))

    async def _guarded():
        return await async_lookup_ip(session, "ipapi", DOC)

    result = asyncio.run(_guarded())
    assert result.status == "skipped"
    assert session.urls == []

    ipapi = interpret_response(
        "ipapi",
        200,
        {
            "ip": DOC,
            "country_name": "Exampleland",
            "country": "EX",
            "region": "Example Region",
            "city": "Example City",
            "asn": "AS64500",
            "org": "Example Operator",
            "latitude": "1.5",
            "longitude": 2,
            "timezone": "Etc/UTC",
            "currency": "X",
            "languages": ["en", "es"],
            "postal": "00000",
            "company_secret_field": "SENTINEL_EXTRA",
        },
        {},
        None,
    )
    assert ipapi.status == "complete"
    assert ipapi.fields["country"] == "Exampleland"
    assert ipapi.fields["country_code"] == "EX"
    assert ipapi.fields["asn"] == "AS64500"
    assert ipapi.fields["languages"] == "en,es"
    assert "SENTINEL_EXTRA" not in json.dumps(ipapi.fields)
    assert DOC not in json.dumps(ipapi.fields)

    rate = interpret_response("ipapi", 200, {"error": True, "reason": "RateLimited"}, {"Retry-After": "30"}, None)
    assert rate.status == "rate_limited"
    assert rate.retry_after == 30.0
    assert interpret_response("ipapi", 429, {}, {}, None).status == "rate_limited"
    assert interpret_response("ipapi", 200, {"reserved": True, "ip": DOC}, {}, None).status == "skipped"
    info = interpret_response(
        "ipinfo",
        200,
        {"org": "AS64500 Example Operator", "loc": "1.25,2.5", "country": "EX", "city": "Example City", "bogon": False},
        {},
        None,
    )
    assert info.status == "complete"
    assert info.fields["asn"] == "AS64500"
    assert info.fields["org"] == "Example Operator"
    assert info.fields["latitude"] == 1.25
    assert info.fields["longitude"] == 2.5
    assert info.fields["country_code"] == "EX"
    assert interpret_response("ipinfo", 200, {"bogon": True}, {}, None).status == "skipped"
    assert interpret_response("ipinfo", 200, {"error": {"title": "Unknown request"}}, {}, None).status == "error"
    assert interpret_response("ipapi", None, None, {}, "invalid_json").status == "error"

    provider = IPInfo(DOC)
    provider.result = {"org": "AS64500"}
    assert provider.asn == "AS64500"
    assert provider.org is None


def test_http_reader_does_not_follow_redirects_or_log_the_address(caplog, monkeypatch):
    import custom_components.authenticated.providers as providers

    body = {"city": "Example City", "country_name": "Exampleland", "country_code": "EX"}
    session = _FakeSession(_FakeResponse(200, body))

    async def _read():
        return await read_http(session, "https://ipapi.co/203.0.113.10/json")

    status, payload, _headers, failure = asyncio.run(_read())
    assert status == 200
    assert payload["city"] == "Example City"
    assert failure is None
    assert session.kwargs[0]["allow_redirects"] is False

    monkeypatch.setattr(providers, "enrichment_allowed", lambda _ip: True)
    failing = _FakeSession(error=aiohttp.ClientError("https://ipapi.co/203.0.113.10/json " + TOKEN_SENTINEL))
    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(async_lookup_ip(failing, "ipapi", DOC))
    assert outcome.status == "error"
    assert DOC not in caplog.text
    assert TOKEN_SENTINEL not in caplog.text
    assert "transport" in caplog.text


def test_session_does_not_trust_the_environment():
    async def _open():
        session = create_session()
        try:
            assert session.trust_env is False
        finally:
            await session.close()

    asyncio.run(_open())


def test_shutdown_cancels_tasks_and_closes_the_session():
    async def _run():
        life = Lifecycle()
        called = []
        life.track_unsub(lambda: called.append("unsub"))

        async def _sleep():
            await asyncio.sleep(30)

        task = asyncio.create_task(_sleep())
        life.track_task(task)

        class _Session:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        session = _Session()
        life.session = session
        await life.async_shutdown()
        await life.async_shutdown()
        assert called == ["unsub"]
        assert task.cancelled()
        assert session.closed

    asyncio.run(_run())


def test_form_schema_uses_probatio_not_a_stub():
    """The form schema must validate without the voluptuous test stub."""
    from custom_components.authenticated.form_schema import build_form_schema
    from custom_components.authenticated.settings import storage_from_form

    defaults = storage_from_form(
        {
            "provider": "ipapi",
            "notify_services": "notify.mobile_app_example",
            "exclude": "203.0.113.0/24",
            "history_retention_days": 30,
            "history_max_events": 200,
        }
    )
    for field in (
        "notify_services",
        "exclude",
        "exclude_clients",
        "notify_exclude_asns",
        "notify_exclude_hostnames",
    ):
        defaults[field] = ", ".join(defaults[field])
    schema = build_form_schema(defaults)
    parsed = schema(defaults)
    assert parsed["notify_services"] == "mobile_app_example"
    assert parsed["exclude"] == "203.0.113.0/24"
    assert parsed["enrich_public_ips"] is True
    assert parsed["store_usernames"] is False
    assert parsed["history_retention_days"] == 30


def test_runtime_is_registered_before_platform_setup():
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "custom_components",
        "authenticated",
        "__init__.py",
    )
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    setup = source.split("async def async_setup_entry", 1)[1].split(
        "async def async_unload_entry", 1
    )[0]
    store_at = setup.index("hass.data[DOMAIN][entry.entry_id] = runtime")
    forward_at = setup.index("await hass.config_entries.async_forward_entry_setups")
    assert store_at < forward_at


def test_repository_does_not_parse_forwarded_headers():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "custom_components", "authenticated")
    for name in os.listdir(root):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, name), encoding="utf-8") as handle:
            text = handle.read()
        assert "X-Forwarded-For" not in text
        assert "x_forwarded_for" not in text
        assert "import requests" not in text
        assert "import voluptuous" not in text
