"""Constants for eufy_sdk."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "eufy_sdk"
ATTRIBUTION = "Data provided by the eufy cloud via ha-eufy-sdk-bridge"

# Config-entry keys: the address of the ha-eufy-sdk-bridge WebSocket.
CONF_HOST = "host"
CONF_PORT = "port"
DEFAULT_PORT = 3000

# Schema version this integration targets (the bridge sends its own in `hello`/`ready`).
SUPPORTED_SCHEMA = 1
