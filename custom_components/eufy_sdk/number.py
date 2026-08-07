"""Number platform — one number per writable numeric property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.number import NumberEntity, NumberMode

from .entity import EufySdkPropertyEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

# The manifest carries no min/max, so pick a sane range from the value's `kind`.
_RANGE_BY_KIND = {"percent": (0, 100), "seconds": (0, 86400), "degrees": (0, 360)}
_DEFAULT_RANGE = (0, 65535)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a number for every writable numeric property."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        EufySdkNumber(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if spec.get("type") == "number" and spec.get("writable")
    )


class EufySdkNumber(EufySdkPropertyEntity, NumberEntity):
    """A writable numeric property as a number."""

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Set the unit + a range inferred from the value's kind."""
        super().__init__(coordinator, sn, spec)
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        low, high = _RANGE_BY_KIND.get(spec.get("kind"), _DEFAULT_RANGE)
        self._attr_native_min_value = low
        self._attr_native_max_value = high

    @property
    def native_value(self) -> float | None:
        """The property's current numeric value."""
        v = self.prop_value
        return float(v) if isinstance(v, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Write the value (as an int when it's whole, to match the wire)."""
        await self.write(int(value) if value == int(value) else value)
