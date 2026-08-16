"""Sensor platform — a diagnostic Info sensor plus one per read-only scalar property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory

from .bespoke import BITFIELD_SWITCHES
from .entity import EufySdkDeviceEntity, EufySdkPropertyEntity, classify

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry


def _is_sensor(spec: dict) -> bool:
    """Return True for classify()=="sensor", plus bitfields with no bespoke switches."""
    kind = classify(spec)
    if kind == "sensor":
        return True
    return kind == "bitfield" and spec["name"] not in BITFIELD_SWITCHES


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create an Info sensor per device, plus a sensor per property routed here."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        EufySdkInfoSensor(coordinator, sn) for sn in coordinator.data
    ]
    entities.extend(
        EufySdkPropertySensor(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if _is_sensor(spec)
    )
    async_add_entities(entities)


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


class EufySdkPropertySensor(EufySdkPropertyEntity, SensorEntity):
    """A read-only number / string / enum property as a sensor."""

    # Read-only telemetry (battery, wifi, firmware, codes, unsplit bitfields) belongs
    # under Diagnostics, not the main Controls area — matching the old eufy integration.
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Set unit + device/state class from the value's kind."""
        super().__init__(coordinator, sn, spec)
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        kind = spec.get("kind")
        if kind == "percent":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if "battery" in self._prop.lower():
                self._attr_device_class = SensorDeviceClass.BATTERY
        elif kind == "dbm":
            self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif kind == "celsius":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        """Current value; enums render as their label, structured values are dropped."""
        v = self.prop_value
        if v is None:
            return None
        enum = self._spec.get("enumValues")
        if enum:
            return enum.get(str(v), v) if isinstance(v, (int, str)) else None
        return v if isinstance(v, (int, float, str)) else None
