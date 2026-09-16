"""Constants for eufy_sdk."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "eufy_sdk"
ATTRIBUTION = "Data provided by the eufy cloud via ha-eufy-sdk-bridge"

# Config-entry keys: the address of the ha-eufy-sdk-bridge WebSocket.
CONF_HOST = "host"
CONF_PORT = "port"
DEFAULT_PORT = 3000

# Options: how often the bridge polls the cloud for device state (minutes).
# Drives both the bridge's cloud poll (config.set) and how often HA reads it.
CONF_POLL_INTERVAL = "poll_interval_minutes"
DEFAULT_POLL_INTERVAL_MIN = 10

# Options: how often HA re-reads a Solarbank's SOC limits from the cloud (seconds).
# The discharge/charge limits arrive reliably only via this authoritative HTTP read
# (the b5 telemetry carries them only on an occasional settings frame), so this is the
# cadence an app-side SOC change reflects on the sliders.
CONF_SOC_REFRESH = "soc_refresh_seconds"
DEFAULT_SOC_REFRESH_SEC = 60

# Schema version this integration targets (the bridge sends its own in `hello`/`ready`).
SUPPORTED_SCHEMA = 1

# Stored PTZ preset slots offered per pan-tilt camera. Eight is what the SDK sees on
# the models it has observed (an unused slot reports `enable: 0`). Models differ, but
# referencing an empty slot is a silent no-op on the wire, so offering eight costs
# nothing where there are fewer — the camera ignores what it has no position for.
PTZ_PRESET_SLOTS = 8
