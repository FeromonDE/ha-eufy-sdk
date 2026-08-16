"""Image platform — the latest detected-event thumbnail, one per camera."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_PORT, DOMAIN
from .entity import EufySdkDeviceEntity

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

# Bridge device events are re-fired on the HA bus under this type (see __init__.py).
EVENT_TYPE = f"{DOMAIN}_event"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a latest-event image for every device the bridge exposes as a camera."""
    coordinator = entry.runtime_data.coordinator
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    async_add_entities(
        EufySdkEventImage(hass, coordinator, sn, host, port)
        for sn, dev in coordinator.data.items()
        if dev.get("stream")
    )


class EufySdkEventImage(EufySdkDeviceEntity, ImageEntity):
    """
    Latest-detection-event thumbnail for one device.

    On a detection event the SDK downloads and retains the event's thumbnail; the
    bridge serves the retained bytes at `/event-image/<sn>`. This entity fetches from
    the bridge (never the raw cloud URL — that needs the SDK's auth/decode), and a
    detection event on the HA bus tells HA the image changed and to re-fetch.
    """

    _attr_name = "Last event"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        host: str,
        port: int,
    ) -> None:
        """Bind to a device serial + the bridge address."""
        EufySdkDeviceEntity.__init__(self, coordinator, sn)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{sn}_last_event"
        self._url = f"http://{host}:{port}/event-image/{sn}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to bridge device events while the entity is registered."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_TYPE, self._handle_event))

    @callback
    def _handle_event(self, event: Event) -> None:
        """Mark the image stale when this device reports an event with a thumbnail."""
        data = event.data
        if data.get("deviceSn") != self._sn or not data.get("thumbnailUrl"):
            return
        # A new timestamp tells HA the image changed and to re-fetch it from the bridge.
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Fetch the retained thumbnail from the bridge (called by HA's image proxy)."""
        session = async_get_clientsession(self.hass)
        try:
            resp = await session.get(self._url, timeout=aiohttp.ClientTimeout(total=15))
            if resp.status != HTTPStatus.OK:
                return None
            return await resp.read()
        except (aiohttp.ClientError, TimeoutError):
            return None
