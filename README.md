# ha-eufy-sdk

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=home-assistant&logoColor=white)](https://hacs.xyz)
[![Validate](https://github.com/mega-yfue/ha-eufy-sdk/actions/workflows/validate.yml/badge.svg)](https://github.com/mega-yfue/ha-eufy-sdk/actions/workflows/validate.yml)
[![Lint](https://github.com/mega-yfue/ha-eufy-sdk/actions/workflows/lint.yml/badge.svg)](https://github.com/mega-yfue/ha-eufy-sdk/actions/workflows/lint.yml)
[![release](https://img.shields.io/github/v/release/mega-yfue/ha-eufy-sdk?sort=semver)](https://github.com/mega-yfue/ha-eufy-sdk/releases)
[![license](https://img.shields.io/github/license/mega-yfue/ha-eufy-sdk)](./LICENSE)

The Home Assistant integration for eufy — installed via **HACS**. This is the front door: it talks to
the [`ha-eufy-sdk-bridge`](https://github.com/mega-yfue/ha-eufy-sdk-bridge) over WebSocket and turns
every device the bridge reports into HA entities (cameras, sensors, switches, locks, …), with live
video via the bridge's bundled go2rtc.

- **Config flow**: point it at a bridge URL, or let it auto-discover the add-on via the Supervisor.
- **Entities** are derived from each device's `capabilities` — no per-device Python.
- **Video** uses `stream_source()` → go2rtc → WebRTC, so a camera streams with nothing extra installed.

`custom_components/eufy_sdk/`

## Install

In HACS → **Custom repositories**, add this repo as an *Integration*, install, then add **eufy-sdk**
from **Settings → Devices & Services**.

## Where it fits

| Repo | Role |
| --- | --- |
| [`eufy-sdk`](https://github.com/mega-yfue/eufy-sdk) | the HA-agnostic library |
| [`ha-eufy-sdk-bridge`](https://github.com/mega-yfue/ha-eufy-sdk-bridge) | WS + HTTP + go2rtc daemon (Docker) |
| [`ha-eufy-sdk-addon`](https://github.com/mega-yfue/ha-eufy-sdk-addon) | Home Assistant add-on wrapper |
| **`ha-eufy-sdk`** | **this** — the HACS integration (front door) |

> Status: scaffolding. The config flow + entity platforms land next.
