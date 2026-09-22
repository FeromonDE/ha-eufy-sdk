"""Camera platform — a live camera per streaming device, via the bridge's go2rtc."""

from __future__ import annotations

import asyncio
import contextlib
from http import HTTPStatus
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    CONF_GO2RTC_RTSP_PORT,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_GO2RTC_RTSP_PORT,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a camera for every device the bridge marked with a `stream` path."""
    coordinator = entry.runtime_data.coordinator
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    rtsp_port = int(entry.data.get(CONF_GO2RTC_RTSP_PORT, DEFAULT_GO2RTC_RTSP_PORT))
    async_add_entities(
        EufySdkCamera(coordinator, sn, host, port, rtsp_port)
        for sn, dev in coordinator.data.items()
        if dev.get("stream")
    )

    # Match the legacy fuatakgun/eufy_security camera API: explicit entity services
    # for P2P and native-device RTSP live streams.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "start_p2p_livestream", {}, "async_start_p2p_livestream"
    )
    platform.async_register_entity_service(
        "stop_p2p_livestream", {}, "async_stop_p2p_livestream"
    )
    platform.async_register_entity_service(
        "start_rtsp_livestream", {}, "async_start_rtsp_livestream"
    )
    platform.async_register_entity_service(
        "stop_rtsp_livestream", {}, "async_stop_rtsp_livestream"
    )


class EufySdkCamera(CoordinatorEntity["EufySdkDataUpdateCoordinator"], Camera):
    """A camera via the bridge: live via go2rtc RTSP, stills via snapshot."""

    _attr_has_entity_name = True
    _attr_name = None  # the device name is the camera name
    _attr_attribution = ATTRIBUTION
    _attr_supported_features = (
        CameraEntityFeature.STREAM | CameraEntityFeature.ON_OFF
    )

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        host: str,
        port: int,
        rtsp_port: int,
    ) -> None:
        """Bind to a device serial + the bridge address."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._sn = sn
        self._host = host
        self._port = port
        self._rtsp_port = rtsp_port
        self._stream_provider: str | None = None
        self._native_rtsp_url: str | None = None
        self._attr_unique_id = f"{sn}_camera"
        dev = coordinator.data.get(sn, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name=dev.get("name") or sn,  # the user's device name (e.g. "Dining room")
            manufacturer="eufy",
            model=dev.get("model") or dev.get("codec"),  # the model code, not the codec
            serial_number=sn,
        )

    @property
    def available(self) -> bool:
        """Available while the bridge still reports this camera."""
        return super().available and self._sn in self.coordinator.data

    @property
    def is_on(self) -> bool:
        """Return whether this camera entity has an explicitly requested live stream."""
        return self._stream_provider is not None

    @property
    def is_streaming(self) -> bool:
        """Return whether this entity currently owns a live stream."""
        if self._stream_provider == "rtsp":
            return bool(self.device.get("state", {}).get("rtspStream"))
        if self._stream_provider == "p2p":
            return bool(self.device.get("streaming")) or self.stream is not None
        return False

    async def stream_source(self) -> str | None:
        """Return the active provider URL; None until an explicit start/turn-on."""
        if self._stream_provider == "rtsp":
            return self._native_rtsp_url or self.device.get("state", {}).get("rtspUrl")
        if self._stream_provider == "p2p":
            return f"rtsp://{self._host}:{self._rtsp_port}/{self._sn}"
        return None

    @property
    def _rtsp_supported(self) -> bool:
        """Whether the SDK property manifest exposes native RTSP publication."""
        specs = self.coordinator.config_entry.runtime_data.properties.get(self._sn, [])
        return any(spec.get("name") == "rtspStream" for spec in specs)

    async def _start_hass_streaming(self) -> None:
        """Create/start HA's stream consumer, matching fuatakgun's camera lifecycle."""
        await self._stop_hass_streaming()
        stream = await self.async_create_stream()
        if stream is None:
            raise HomeAssistantError("Camera stream source is unavailable")
        await stream.start()

    async def _stop_hass_streaming(self) -> None:
        """Stop HA's stream consumer so go2rtc releases the upstream feed."""
        if self.stream is not None:
            await self.stream.stop()
            self.stream = None

    async def async_start_p2p_livestream(self) -> None:
        """Start the P2P live stream through bridge go2rtc, like legacy Start P2P."""
        client = self.coordinator.config_entry.runtime_data.client
        await self._stop_hass_streaming()
        self._native_rtsp_url = None
        self._stream_provider = "p2p"
        try:
            await client.start_stream(self._sn)
            # Opening this RTSP consumer is the operation that makes bridge/go2rtc
            # open the SDK's real P2P LiveStream.
            await self._start_hass_streaming()
        except Exception:  # noqa: BLE001 - rollback then preserve the original failure
            self._stream_provider = None
            with contextlib.suppress(Exception):
                await client.stop_stream(self._sn)
            raise
        finally:
            self.async_write_ha_state()

    async def async_stop_p2p_livestream(self) -> None:
        """Stop the P2P stream by releasing HA's media consumer."""
        client = self.coordinator.config_entry.runtime_data.client
        await self._stop_hass_streaming()
        self._stream_provider = None
        self._native_rtsp_url = None
        # The media disconnect above is the real stop; keep the bridge command too
        # because it is the protocol counterpart and mirrors the legacy service.
        await client.stop_stream(self._sn)
        self.async_write_ha_state()

    async def _wait_for_rtsp_url(self) -> str:
        """Wait for the authoritative RTSP URL pushed by the device after publish."""
        client = self.coordinator.config_entry.runtime_data.client
        async with asyncio.timeout(15):
            while True:
                dev = await client.get_device(self._sn)
                state = dev.get("state", {})
                url = state.get("rtspUrl")
                if isinstance(url, str) and url.startswith("rtsp://"):
                    return url
                await asyncio.sleep(0.5)

    async def async_start_rtsp_livestream(self) -> None:
        """Start the camera's native RTSP publication and consume it in HA."""
        if not self._rtsp_supported:
            raise HomeAssistantError("Camera does not support native RTSP")
        client = self.coordinator.config_entry.runtime_data.client
        await self._stop_hass_streaming()
        await client.set_property(self._sn, "rtspStream", True)
        try:
            self._native_rtsp_url = await self._wait_for_rtsp_url()
            self._stream_provider = "rtsp"
            await self._start_hass_streaming()
        except Exception:
            self._stream_provider = None
            self._native_rtsp_url = None
            with contextlib.suppress(Exception):
                await client.set_property(self._sn, "rtspStream", False)
            raise
        finally:
            self.async_write_ha_state()

    async def async_stop_rtsp_livestream(self) -> None:
        """Stop HA consumption and disable the camera's native RTSP publication."""
        client = self.coordinator.config_entry.runtime_data.client
        await self._stop_hass_streaming()
        await client.set_property(self._sn, "rtspStream", False)
        self._stream_provider = None
        self._native_rtsp_url = None
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Use RTSP when already enabled on-device, otherwise fall back to P2P."""
        rtsp_enabled = self.device.get("state", {}).get("rtspStream") is True
        if self._rtsp_supported and rtsp_enabled:
            await self.async_start_rtsp_livestream()
        else:
            await self.async_start_p2p_livestream()

    async def async_turn_off(self) -> None:
        """Stop the currently selected stream provider."""
        if self._stream_provider == "rtsp":
            await self.async_stop_rtsp_livestream()
        else:
            await self.async_stop_p2p_livestream()

    async def async_camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Return a still from the bridge's /snapshot endpoint."""
        session = async_get_clientsession(self.hass)
        url = f"http://{self._host}:{self._port}/snapshot/{self._sn}"
        try:
            async with session.get(url, timeout=20) as resp:
                if resp.status == HTTPStatus.OK:
                    return await resp.read()
        except (TimeoutError, OSError):
            return None
        return None
