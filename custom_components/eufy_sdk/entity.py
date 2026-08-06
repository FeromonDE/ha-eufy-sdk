"""Base entity for eufy_sdk — one HA device per eufy device (keyed by serial)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import EufySdkDataUpdateCoordinator


class EufySdkDeviceEntity(CoordinatorEntity[EufySdkDataUpdateCoordinator]):
    """An entity attached to one eufy device (`sn`), driven by the bridge device list."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a device serial and build its HA device_info."""
        super().__init__(coordinator)
        self._sn = sn
        dev = coordinator.data.get(sn, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name=dev.get("name") or sn,
            manufacturer="eufy",
            model=dev.get("codec"),
            serial_number=sn,
        )

    @property
    def device(self) -> dict:
        """The latest device record from the coordinator (sn/name/codec/capabilities/stream)."""
        return self.coordinator.data.get(self._sn, {})

    @property
    def available(self) -> bool:
        """Available while the bridge still reports this device."""
        return super().available and self._sn in self.coordinator.data
