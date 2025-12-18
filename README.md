# Authenticated – Home Assistant Integration

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/SupaHotMoj0/authenticated?style=for-the-badge)](https://github.com/SupaHotMoj0/authenticated/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](LICENSE)

Track successful Home Assistant authentication events and expose them as a sensor, enriched with IP address intelligence, geolocation data, ASN information, and user context.

This integration monitors Home Assistant authentication activity and provides insight into *who logged in, from where, and when*.

---

## 🔥 New & Enhanced Features

- Full **UI configuration via Config Flow** (no YAML required)
- Real-time authentication event tracking
- Automatic IP detection and enrichment
- Detailed geolocation (country, region, city)
- ASN and ISP / organisation lookup
- Hostname resolution
- Optional persistent notifications for new IPs
- Per-IP audit history stored locally
- Exclusion controls for IPs, ASNs, hostnames, and clients
- Fully async and event-driven (no blocking I/O)

---

## Description

`authenticated` is a Home Assistant sensor platform that tracks **successful logins** and exposes the **most recent authentication** as a sensor entity.

Each authentication is enriched using a selectable IP intelligence provider, allowing you to understand where access originates and whether it matches expected networks.

The integration supports both **UI-based setup** and **legacy YAML configuration**.

---

## Sensor

### Entity

sensor.last_successful_authentication

### State

<IP address>

### Attributes

- username
- hostname
- country
- country_code
- region
- city
- asn
- org
- latitude
- longitude
- timezone
- currency
- languages
- postal
- new_ip
- last_authenticated_time
- previous_authenticated_time

---

## Supported Providers

| Provider | Description |
|----------|-------------|
| ipapi | Default provider with rich ASN and ISP data |
| ipinfo | Lightweight alternative provider |

Providers are modular and can be extended.

---

## Installation

### Manual installation

1. Copy the authenticated directory to:
   ```
   custom_components/authenticated/
   ```

2. Restart Home Assistant

3. Add the integration via:
   ```
   Settings → Devices & Services → Add Integration → Authenticated
   ```

---

## Configuration (UI – Recommended)

The integration supports full configuration via the Home Assistant UI.

**Configurable options:**

- Enable or disable notifications
- Select IP lookup provider
- Exclude IP addresses or networks
- Exclude ASNs from notifications
- Exclude hostnames from notifications
- Optional logfile path

All options can be modified after setup.

---

## Configuration (YAML – Optional)

```yaml
sensor:
  - platform: authenticated
    provider: ipapi
    enable_notification: true
    exclude:
      - 192.168.1.0/24
    notify_exclude_asns:
      - AS12345
    notify_exclude_hostnames:
      - localhost
```

---

## Data Storage

Authentication metadata is written to:

```
.ip_authenticated.yaml
```

This file stores:

- IP address
- User and username
- Geo information
- ASN and organisation
- Hostname
- First and last seen timestamps

Useful for auditing and historical analysis.

---

## Privacy & Security

- No credentials are stored
- Only successful authentications are processed
- Uses Home Assistant's internal authentication data
- Local-only operation
- External IP lookups are configurable

---

## File Structure

```
authenticated/
├── __init__.py
├── sensor.py
├── providers.py
├── config_flow.py
├── const.py
├── manifest.json
└── .ip_authenticated.yaml
```

---

## Development

Pull requests are welcome.

When contributing:

- Keep code async-safe
- Avoid blocking I/O
- Follow Home Assistant integration guidelines

---

## Issues

Please report issues here: https://github.com/SupaHotMoj0/authenticated/issues

Include logs and Home Assistant version when possible.

---

## Credits

This project builds upon the original work by:

- @rarosalion
- @ludeeus

Much love and respect for laying the foundation this integration is built on ❤️

---

## License

MIT License
