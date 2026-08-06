"""Sensor platform — one diagnostic 'info' sensor per device, so every eufy device appears in HA."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .entity import EufySdkDeviceEntity

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
    """Create one info sensor per device the bridge reported."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(EufySdkInfoSensor(coordinator, sn) for sn in coordinator.data)


class EufySdkInfoSensor(EufySdkDeviceEntity, SensorEntity):
    """A diagnostic sensor: value = the device codec, attributes = its capabilities."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Name it '<device> Info'."""
        super().__init__(coordinator, sn)
        self._attr_unique_id = f"{sn}_info"
        self._attr_name = "Info"

    @property
    def native_value(self) -> str | None:
        """The device's wire-protocol family (camera / station / sensor / …)."""
        return self.device.get("codec")

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the capability list + serial for a host to inspect."""
        return {"serial": self._sn, "capabilities": self.device.get("capabilities", [])}
