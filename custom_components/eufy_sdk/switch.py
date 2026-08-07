"""Switch platform — writable booleans, plus per-bit switches for known bitfields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .bespoke import BITFIELD_SWITCHES
from .entity import EufySdkPropertyEntity, classify

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
    """Create a switch per writable bool, and per-bit switches for known bitfields."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SwitchEntity] = []
    for sn in coordinator.data:
        for spec in entry.runtime_data.properties.get(sn, []):
            kind = classify(spec)
            if kind == "switch":
                entities.append(EufySdkSwitch(coordinator, sn, spec))
            elif kind == "bitfield" and spec["name"] in BITFIELD_SWITCHES:
                bf = BITFIELD_SWITCHES[spec["name"]]
                entities.extend(
                    EufyBitmaskSwitch(
                        coordinator,
                        sn,
                        spec,
                        {"label": label, "bit": bit, "base": bf["base"]},
                    )
                    for label, bit in bf["bits"].items()
                )
    async_add_entities(entities)


class EufySdkSwitch(EufySdkPropertyEntity, SwitchEntity):
    """A writable boolean property as a switch."""

    @property
    def is_on(self) -> bool | None:
        """On when the property's live value is truthy."""
        v = self.prop_value
        return None if v is None else bool(v)

    async def async_turn_on(self, **_: Any) -> None:
        """Set the property true."""
        await self.write(value=True)

    async def async_turn_off(self, **_: Any) -> None:
        """Set the property false."""
        await self.write(value=False)


class EufyBitmaskSwitch(EufySdkPropertyEntity, SwitchEntity):
    """One bit of a bitfield property as a switch (writes back the whole mask)."""

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
        bitdef: dict[str, Any],
    ) -> None:
        """Bind to a single bit of the parent bitfield property ({label, bit, base})."""
        super().__init__(coordinator, sn, spec)
        self._bit: int = bitdef["bit"]
        self._base: int = bitdef["base"]
        self._attr_unique_id = f"{sn}_{self._prop}_{self._bit}"
        self._attr_name = bitdef["label"]

    def _mask(self) -> int:
        """Return the current full bitmask value (falls back to the enable base)."""
        v = self.prop_value
        return int(v) if isinstance(v, (int, float)) else self._base

    @property
    def is_on(self) -> bool | None:
        """On when this bit is set in the current mask."""
        v = self.prop_value
        return None if v is None else bool(int(v) & self._bit)

    async def async_turn_on(self, **_: Any) -> None:
        """Set this bit (keeping the enable base and the other bits)."""
        await self.write(self._mask() | self._bit | self._base)

    async def async_turn_off(self, **_: Any) -> None:
        """Clear this bit (keeping the enable base and the other bits)."""
        await self.write((self._mask() & ~self._bit) | self._base)
