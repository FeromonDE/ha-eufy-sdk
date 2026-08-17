"""DataUpdateCoordinator for eufy_sdk — owns the bridge connection + the device list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EufySdkApiClientAuthenticationError, EufySdkApiClientError

if TYPE_CHECKING:
    from .data import EufySdkConfigEntry


class EufySdkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Keep the bridge connected and expose the device list as `{sn: device}`."""

    config_entry: EufySdkConfigEntry

    async def _async_update_data(self) -> dict[str, dict]:
        """Ensure the connection is up, confirm we're authed, and return the devices."""
        client = self.config_entry.runtime_data.client
        try:
            if not client.connected:
                await client.connect()
            auth = await client.auth_status()
            state = auth.get("state")
            if state in ("require_2fa", "require_captcha"):
                # Genuinely needs the user — start the reauth flow.
                msg = f"bridge needs re-authentication (state: {state})"
                raise ConfigEntryAuthFailed(msg)
            if state != "ok":
                # Transient: the bridge is still booting/logging in ("pending" after a
                # restart). Retry next interval instead of freezing the entry in reauth;
                # one boot-window poll must not stop updates indefinitely.
                msg = f"bridge not ready yet (state: {state})"
                raise UpdateFailed(msg)
            devices = await client.list_devices()
        except EufySdkApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(err) from err
        except EufySdkApiClientError as err:
            raise UpdateFailed(err) from err
        return {d["sn"]: d for d in devices if d.get("sn")}
