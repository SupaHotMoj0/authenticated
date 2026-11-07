# Authenticated

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/SupaHotMoj0/authenticated?style=for-the-badge)](https://github.com/SupaHotMoj0/authenticated/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](LICENSE)

Home Assistant custom integration that watches refresh-token use and exposes the latest observed address as a sensor. Public addresses can be enriched with geo and network data. Notifications can go to the persistent notification panel and to notify services you name, such as a mobile app.

The sensor's historical name is still "Last successful authentication". The attributes `observation_type: token_use` and `confirmed_login: false` are the accurate description. Read the limits below before treating a change as a login.

## What is observed

The integration reads `.storage/auth` about once a minute. It looks at each refresh token's `last_used_at` and `last_used_ip`. Those fields are the ones Home Assistant itself stored.

Checked against the Home Assistant Core **2026.11.0** source:

- Creating an access token from a refresh token calls `async_log_refresh_token_usage` and stores `request.remote` as `last_used_ip`.
- `request.remote` is the client address after Home Assistant's trusted-proxy middleware. This integration does not read `X-Forwarded-For` or any other forwarding header.
- On the 2026.11.0 release, a normal refresh token is updated when it is exchanged for an access token (the code exchange after an interactive sign-in, and later refreshes). Access tokens last 30 minutes (`ACCESS_TOKEN_EXPIRATION`).
- On that same release, a long-lived access token does not update `last_used_at` on each request. Later development builds started recording long-lived token use and throttling the disk write. This integration only sees whatever is already in the file.
- There is no public Home Assistant event that covers every successful sign-in. `process_success_login` only clears the failed-login counter.

The file is opened read-only. The integration never writes `.storage/auth`, never copies `token` or `jwt_key`, and never parses proxy headers to "correct" an address. If trusted proxies are wrong, Home Assistant stores the proxy address and this integration shows that address.

A poll can miss activity. Home Assistant keeps only the latest `last_used_at` per token, and it can wait before flushing the file. Two uses between polls become one observation: the later timestamp. Token use is not proof that someone typed a password.

## External enrichment and retention

When **Look up public IP addresses** is on (the default), each globally routable address is sent once per cache window to the provider you pick:

| Provider | Request |
| --- | --- |
| `ipapi` (default) | `https://ipapi.co/<address>/json` |
| `ipinfo` | `https://ipinfo.io/<address>/json` |

The request is an HTTPS GET. The address is in the URL. No Home Assistant token, user id, or password is sent. Redirects are not followed. Private, loopback, link-local, multicast, reserved, shared (carrier-grade NAT, `100.64.0.0/10`), and documentation addresses are stored locally and are not sent.

Lookups use a short timeout, at most 3 addresses per poll, and a capped backoff. A rate limit pauses the provider for at least 15 minutes. After 4 failed attempts the address waits 24 hours. A successful result is kept for 7 days. Failures are logged as a provider name and a status, without the address.

Local history defaults:

| Control | Default |
| --- | --- |
| Retention | 30 days (1–365) |
| Maximum events | 200 (10–1000) |
| Store usernames in the history file | Off |
| Reverse DNS | Off |
| Mobile notify services | None |
| Persistent notification | On |
| Notify when | A new address, or the same address used by a different user |

The history file is `.ip_authenticated.yaml` in the config directory, mode `0600`. It holds a version-2 event list and a per-address summary. Usernames are left out unless you turn **Store usernames** on. Turning that option off removes usernames from the active file on the next poll. The file stores a short hash of the refresh-token id and of the user id so a later poll can match the same record. It does not store the token secret, the JWT key, the client id, or the raw user id.

The sensor still shows the current username from the live auth file, because that is what the entity is for. Home Assistant's recorder will store the sensor state and attributes, including the latest address and username, unless you exclude the entity in the recorder. The full event list is not copied into the entity attributes.

Notifications contain the address, the user name when it is known, and a line stating that the event is token use rather than a confirmed interactive login. Each notify service is called on its own. One failure does not cancel the others. Service names must look like `mobile_app_example` or `notify.mobile_app_example` (up to 8). The examples are placeholders, not devices on any particular system.

## Install

These steps do not assume you already use HACS. Use one path. The target system for this release is Home Assistant OS 2026.11.0. The same files are what a Raspberry Pi 5 running that OS would load. This repository's automated tests do not boot that system.

### Before you update an existing install

1. Back up the config directory, or at least copy these if they exist:
   - `/config/.ip_authenticated.yaml`
   - `/config/custom_components/authenticated/`
2. Do not publish those copies. The yaml file can contain addresses and, on older versions, usernames.

On Home Assistant OS the config directory is `/config` in the SSH and Studio Code add-ons, and `config` in the File editor and Samba share.

`hacs.json` sets `homeassistant` to `2026.9.0`. That is the minimum version HACS and the Marketplace use when they decide whether a release can be installed. Home Assistant Core tag `2026.9.0` lists `probatio==0.11.4` in `requirements.txt`, and `homeassistant/__init__.py` on that tag calls `install_as_voluptuous()`. This repository's automated tests were not run on Core 2026.9.0, so the key is a version floor, not a compatibility test result. The integration version in `manifest.json` stays `1.1.0`.

This repository is not in the default Marketplace or HACS catalog. Adding it from a link does not mean it was accepted into that catalog.

### Home Assistant 2026.11 or newer

The Marketplace ships with Home Assistant 2026.11 under **Settings → Marketplace**. HACS, the separate custom integration, cannot be installed on this version.

1. Open **Settings → Marketplace** as an administrator and accept the community-content notice. Installing stays blocked until that notice is accepted.
2. Select **Add from link** and enter `https://github.com/SupaHotMoj0/authenticated`.
3. If the Marketplace asks for a type, choose **Integration**, then add it again.
4. A custom repository needs a GitHub connection. The Marketplace uses GitHub's device sign-in: it shows a code and a link, you sign in on GitHub and approve the code. The connection reads public repository information. Catalog installs do not need this step. This repository does, because it is not in the catalog.
5. Open the repository and select **Install**.
6. When Home Assistant can load the integration immediately, its setup page opens and a restart is not required for that first install. If you close the page, add **Authenticated** later under **Settings → Devices & services**. Some integrations only load after a restart. The Marketplace shows a repair when that is the case.
7. After an update, restart Home Assistant. A repair under **Settings → System → Repairs** reminds you and can restart it.

Sources, read 2026-11-07: [Marketplace](https://www.home-assistant.io/integrations/marketplace/) and the [2026.11 release notes](https://www.home-assistant.io/blog/2026/11/04/release-202611/).

### Home Assistant 2026.10 or older

Use HACS. Its own documentation says to keep using HACS on 2026.10 and older.

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/SupaHotMoj0/authenticated` and set the type to **Integration**.
3. Select **ADD**, then download **Authenticated**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → Authenticated**.

The 2026.11 release notes describe that older HACS path as download, restart, then Devices & services. HACS custom-repository steps are documented at [Custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SupaHotMoj0&repository=authenticated&category=Integration)

HACS updates replace `custom_components/authenticated`. They do not delete `.ip_authenticated.yaml`.

### Manual

1. Copy `custom_components/authenticated` to `/config/custom_components/authenticated`.
2. Restart Home Assistant.
3. Add the integration from **Settings → Devices & services → Add integration → Authenticated**.

You only need one config entry. A legacy YAML `sensor:` platform is still accepted, but it does nothing if the UI entry is already set up, so the file is not polled twice.

## Options

Open **Settings → Devices & services → Authenticated → Configure**. Saving reloads the integration. The first setup and Configure use the same fields.

| Option | Role |
| --- | --- |
| IP lookup provider | `ipapi` or `ipinfo` |
| Look up public IP addresses | Turn off to keep every address on the device |
| Persistent notification | Notification panel entry for a new address or a user change |
| When to notify | `new_ip` (default) or `every_observation` |
| Notify services | Comma-separated notify service names |
| Excluded networks | Comma-separated IPs or CIDR ranges. Host bits are accepted (`203.0.113.10` is stored as a single address) |
| Excluded client IDs | Exact client id strings from the auth file. They are not written to the history file |
| Excluded ASNs | Skip the notification when enrichment returns that ASN. Needs enrichment |
| Excluded hostnames | Used only when a hostname is already known |
| History retention and cap | Bounds above |
| Store usernames | Off by default |
| Resolve public hostnames | Off by default. Uses the system resolver and can reveal the address to that resolver |

`ipinfo` returns a country code, not a country name. The country attribute is then the code. `ipapi` returns a country name when the provider has one.

YAML, if you still use it:

```yaml
sensor:
  - platform: authenticated
    provider: ipapi
    enable_notification: true
    enrich_public_ips: true
    notify_on: new_ip
    notify_services:
      - mobile_app_example
    exclude:
      - 203.0.113.0/24
    history_retention_days: 30
    history_max_events: 200
    store_usernames: false
    resolve_hostnames: false
```

`log_location` may be a file name relative to the config directory. Absolute paths, `..`, and anything under `.storage` are ignored so the writer cannot be pointed at the auth file.

## Migration from 1.0.0

Version 1 stored one map of address to latest fields in `.ip_authenticated.yaml`. Version 1.1.0 keeps that path and writes a version-2 document with an event list.

On the first start of 1.1.0, if the file is the old map:

1. The original bytes are copied once to `/config/.ip_authenticated.yaml.v1.bak` (mode `0600`). An existing backup is not overwritten.
2. If that copy fails, the original file is left as-is and the new format is not written.
3. The active file is then replaced with version 2. Existing addresses are seeded so the upgrade does not notify for rows you already had. A newer `last_used_at` than the one in the old file is treated as a new observation.
4. Usernames and raw user ids are not copied into the active file unless **Store usernames** is already on. The `.v1.bak` file still has the previous bytes, including any usernames the old file stored. Delete that backup when you no longer need a downgrade path.
5. Addresses that already had country, city, ASN, or similar data are not looked up again just because you upgraded. Empty public results are retried with the backoff above. Non-public addresses are not sent to a provider.

The first run does not invent a history of older sign-ins. Home Assistant never stored those events. The first poll only records the latest token-use snapshot so later changes can be detected. Events are appended after that.

### Risks

- Starting 1.0.0 again on a version-2 file can corrupt it. Restore `.ip_authenticated.yaml.v1.bak` before you start 1.0.0.
- Retention can make an address look new again after it has been forgotten. That is intentional.
- A burst of token refreshes can exceed the event cap. The oldest retained events are dropped.
- Reading the auth file while Home Assistant is writing it can fail one poll. The previous history is kept and the next poll tries again. The auth file is not rewritten by this integration.
- A mis-configured trusted proxy makes Home Assistant store the proxy address. This integration will not reinterpret headers to replace it.
- Long-lived access tokens on Home Assistant 2026.11.0 may never move `last_used_at` after creation, so they can be invisible here.
- The sensor name still says "authentication" so existing entity IDs stay `sensor.last_successful_authentication`. Automations should use `observation_type` and `confirmed_login` if they need to be precise.

## Check that it is working

Unit tests in this repository do not start Home Assistant OS and were not run on a Raspberry Pi 5.

On the running system:

1. Restart after installing, then confirm **Settings → Devices & services** shows Authenticated without a setup error.
2. In **Developer tools → States**, find `sensor.last_successful_authentication`. Before any token use is seen, the state is unknown and `confirmed_login` is false.
3. Use a normal browser or app session and wait for the next poll (about one minute, and only after Home Assistant has refreshed or created an access token). The state should become an address, `observation_type` should be `token_use`, and `confirmed_login` should stay false.
4. If you had a 1.0.0 file, confirm `.ip_authenticated.yaml.v1.bak` exists and that the active yaml file starts with version `2`.
5. Logs are written without addresses. A geo failure looks like `Geo lookup failed for provider ipapi (http_429)`. Do not paste `.storage/auth`, the history file, tokens, or notification targets into an issue.
6. To confirm the auth file is not being written by this integration, compare its modification time with Home Assistant's own token activity. This integration only reads it. Do not open the file in a tool that rewrites it.

Run the unit tests from a checkout:

```bash
pip install -r requirements-test.txt
python -m pytest
```

Those tests mock the HTTP client. They do not contact ipapi.co or ipinfo.io, and they do not load Home Assistant.

## Roll back

1. Disable the integration or stop Home Assistant so 1.1.0 is not writing the yaml file during the restore.
2. Put the previous `custom_components/authenticated` directory back. The `v1.0.0` git tag matches the previous release.
3. If `.ip_authenticated.yaml.v1.bak` exists, replace `/config/.ip_authenticated.yaml` with that backup **before** starting 1.0.0. Version 1.0.0 expects the old address map.
4. Start Home Assistant.
5. If you only wanted to undo options, use **Configure** and set the previous values instead of rolling back the code. Turning enrichment off stops new provider calls without a downgrade.

Deleting the integration entry does not delete `.ip_authenticated.yaml` or the backup. Remove those files yourself if you want the history gone.

## Sensor

Entity: `sensor.last_successful_authentication`

State: latest address from the auth file, or unknown.

Attributes include the previous geo fields (`country`, `city`, `asn`, `org`, coordinates, and so on), plus:

| Attribute | Meaning |
| --- | --- |
| `observation_type` | Always `token_use` |
| `confirmed_login` | Always false |
| `activity_source` | `auth_storage_refresh_tokens` |
| `ip_scope` | `public`, `private`, `documentation`, and the other special scopes |
| `geo_status` | `complete`, `incomplete`, `skipped`, `rate_limited`, or `error` |
| `last_authenticated_time` | Token `last_used_at`, kept under the old attribute name |
| `last_observed_at` | When this integration noticed that timestamp |
| `history_count` | How many events are still inside the retention cap |
| `new_ip` | True when the latest event was the first time that address was stored |

## Debugging

```yaml
logger:
  default: info
  logs:
    custom_components.authenticated: debug
```

Debug logs include counts, not addresses. Issue reports should include the Home Assistant version and the integration version, not copies of auth storage or the history file.

## Development

The integration code lives in `custom_components/authenticated`. Tests are in `tests/` and run with pytest. They check parsing, backoff, history migration, notification isolation, and that non-public addresses are not requested. They are not a substitute for a Home Assistant OS boot.

## Credits

This project builds on earlier work by [@rarosalion](https://github.com/rarosalion) and [@ludeeus](https://github.com/ludeeus).

## License

[MIT License](LICENSE)
