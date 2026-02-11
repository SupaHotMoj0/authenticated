# Authenticated – Home Assistant Integration

[![Summarize new issues](https://github.com/SupaHotMoj0/authenticated/actions/workflows/summary.yml/badge.svg?event=workflow_dispatch)](https://github.com/SupaHotMoj0/authenticated/actions/workflows/summary.yml)

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/SupaHotMoj0/authenticated?style=for-the-badge)](https://github.com/SupaHotMoj0/authenticated/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](LICENSE)

Track successful Home Assistant authentication events and expose them as a sensor, enriched with IP intelligence, geolocation, ASN data, and user context.

*Who logged in, from where, and when.*

---

## ✨ Features

- 🔐 Real-time **authentication event** tracking via Home Assistant event bus.
- 🌍 Automatic **IP geolocation** enrichment (country, region, city, coordinates).
- 🏢 **ASN and ISP/organisation** lookup per login.
- 🖥️ **Hostname resolution** for each authenticated IP.
- 🔔 Optional **persistent notifications** when a new IP address logs in.
- 🚫 **Exclusion controls** for IPs, networks, ASNs, hostnames, and client IDs.
- 🗂️ **Per-IP audit history** stored locally in `.ip_authenticated.yaml`.
- ⚙️ Full **UI configuration** via Config Flow (no YAML required).
- 📡 Selectable **IP lookup provider** (`ipapi` or `ipinfo`).
- ⚡ Fully **async and event-driven** — no blocking I/O.

---

## 📦 Installation

### HACS (Recommended)

1. Go to **HACS**.
2. Click on the three-dot menu (top right) and select **Custom repositories**.
   1. Set **Repository** to:

      ```text
      https://github.com/SupaHotMoj0/authenticated
      ```

   2. Set **Type** to **Integration**.
   3. Click **ADD**.

3. Search for `authenticated`, select **Authenticated**, click **Download**, and click **Download** again.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration → Authenticated**.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SupaHotMoj0&repository=authenticated&category=Integration)

### Manual Installation

1. Copy the `custom_components/authenticated` folder into your own `config/custom_components/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration → Authenticated**.

---

## 🔧 Configuration

The integration is configured entirely through the Home Assistant UI.

**Options:**

| Option | Description |
|--------|-------------|
| **Provider** | IP lookup provider (`ipapi` or `ipinfo`) |
| **Enable notifications** | Send a persistent notification on new IP logins |
| **Exclude IPs/networks** | Comma-separated IPs or CIDR ranges to ignore |
| **Exclude client IDs** | Comma-separated client IDs to ignore |
| **Exclude ASNs** | ASNs to exclude from notifications |
| **Exclude hostnames** | Hostnames to exclude from notifications |

<details>
<summary>Legacy YAML configuration (optional)</summary>

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

</details>

---

## 📊 Sensor

### Entity

`sensor.last_successful_authentication`

### State

The IP address of the most recent successful login.

### Attributes

| Attribute | Description |
|-----------|-------------|
| `username` | Home Assistant user who authenticated |
| `hostname` | Resolved hostname of the IP |
| `country` | Country name |
| `country_code` | ISO country code |
| `region` | Region / state |
| `city` | City |
| `asn` | Autonomous System Number |
| `org` | ISP / organisation |
| `latitude` | Latitude |
| `longitude` | Longitude |
| `timezone` | Timezone |
| `currency` | Local currency |
| `languages` | Local languages |
| `postal` | Postal / ZIP code |
| `new_ip` | `true` if this IP has not been seen before |
| `last_authenticated_time` | Timestamp of the most recent login |
| `previous_authenticated_time` | Timestamp of the prior login |

---

## 🌐 Supported Providers

| Provider | Description |
|----------|-------------|
| `ipapi` | Default — rich ASN, ISP, and geolocation data |
| `ipinfo` | Lightweight alternative |

Providers are modular and can be extended.

---

## 🗄️ Data Storage

Authentication metadata is persisted to:

```
.ip_authenticated.yaml
```

This file stores per-IP records including user, geo data, ASN, hostname, and first/last seen timestamps. Useful for auditing and historical analysis.

---

## 🐛 Debugging

Add the following to your `configuration.yaml` to enable debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.authenticated: debug
```

---

## 🛠️ Development

Pull requests are welcome.

When contributing:

- Keep code async-safe
- Avoid blocking I/O
- Follow [Home Assistant integration guidelines](https://developers.home-assistant.io/docs/creating_component_index)

---

## 📝 Issues

Report issues at: [github.com/SupaHotMoj0/authenticated/issues](https://github.com/SupaHotMoj0/authenticated/issues)

Include debug logs and your Home Assistant version when possible.

---

## 🙏 Credits

This project builds upon the original work by [@rarosalion](https://github.com/rarosalion) and [@ludeeus](https://github.com/ludeeus).

---

## 📄 License

[MIT License](LICENSE)
