"""Binary sensor platform — one per read-only boolean property (motion, contact, …)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import EufySdkPropertyEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

# Infer a device_class from the property name (substring match, first hit wins).
_DEVICE_CLASS_BY_NAME: list[tuple[str, BinarySensorDeviceClass]] = [
    ("motion", BinarySensorDeviceClass.MOTION),
    ("person", BinarySensorDeviceClass.OCCUPANCY),
    ("contact", BinarySensorDeviceClass.OPENING),
    ("door", BinarySensorDeviceClass.DOOR),
    ("charging", BinarySensorDeviceClass.BATTERY_CHARGING),
    ("battery", BinarySensorDeviceClass.BATTERY),
    ("sound", BinarySensorDeviceClass.SOUND),
    ("online", BinarySensorDeviceClass.CONNECTIVITY),
]


def _device_class(name: str) -> BinarySensorDeviceClass | None:
    low = name.lower()
    return next((dc for key, dc in _DEVICE_CLASS_BY_NAME if key in low), None)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a binary sensor for every read-only boolean property."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        EufySdkBinarySensor(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if spec.get("type") == "bool" and not spec.get("writable")
    )


class EufySdkBinarySensor(EufySdkPropertyEntity, BinarySensorEntity):
    """A read-only boolean property as a binary sensor."""

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Infer a device_class from the property name."""
        super().__init__(coordinator, sn, spec)
        self._attr_device_class = _device_class(self._prop)

    @property
    def is_on(self) -> bool | None:
        """On when the property's live value is truthy."""
        v = self.prop_value
        return None if v is None else bool(v)
