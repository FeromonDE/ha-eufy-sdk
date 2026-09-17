"""Switch platform — writable booleans, plus per-bit switches for known bitfields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .bespoke import BITFIELD_SWITCHES
from .const import DOMAIN
from .entity import EufySdkPropertyEntity, classify, has_capability, is_setting
from .light import LIGHT_OWNED_PROPS

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
        is_smart_light = has_capability(coordinator.data[sn], "smart_light")
        for spec in entry.runtime_data.properties.get(sn, []):
            # The light platform owns lightPower/lightBrightness for smart_light — don't
            # also surface them as a bare switch/number (would double the control).
            if is_smart_light and spec["name"] in LIGHT_OWNED_PROPS:
                continue
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

    # Anker Solix (separate account): a Solarbank's ambient light — a standalone,
    # assumed-state switch (write-only; the AE10x doesn't report the light state).
    solix = getattr(coordinator, "solix_devices", {}) or {}
    entities.extend(
        EufySolixLightSwitch(coordinator, sn)
        for sn, dev in solix.items()
        if "battery" in dev.get("capabilities", [])
    )

    async_add_entities(entities)


class EufySolixLightSwitch(SwitchEntity):
    """
    A Solarbank's ambient light as a switch — ASSUMED STATE (write-only).

    Toggling issues an encrypted `set_device_attrs` write through the bridge, which
    controls the light reliably. But the Solarbank 4 (AE10x) does NOT expose the
    light's on/off anywhere readable — `get_device_attrs` returns nothing for it and
    the `ff09` `ba` byte is constant across toggles (that bitfield was A17C*-only). So
    the switch is assumed-state: it shows the value it last commanded, and a change made
    outside HA (the app / button) can't be reflected. Device is `solix:<sn>`.
    """

    _attr_has_entity_name = True
    _attr_name = "Ambient Light"
    _attr_icon = "mdi:led-strip-variant"
    _attr_assumed_state = True

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a Solix Solarbank; build its Anker Solix HA device_info."""
        self._coordinator = coordinator
        self._sn = sn
        self._on: bool | None = None  # assumed state — the device does not report it
        dev = coordinator.solix_devices.get(sn, {})
        self._attr_unique_id = f"solix_{sn}_ambient_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"solix:{sn}")},
            name=dev.get("name") or sn,
            manufacturer="Anker Solix",
            model=dev.get("productCode"),
            sw_version=dev.get("firmware"),
            serial_number=sn,
        )

    @property
    def is_on(self) -> bool | None:
        """The last value we commanded (assumed state; None until first used)."""
        return self._on

    @property
    def available(self) -> bool:
        """Available while the bridge still lists this Solix device."""
        return self._sn in getattr(self._coordinator, "solix_devices", {})

    async def async_turn_on(self, **_: Any) -> None:
        """Turn the ambient light on (assumed state; device doesn't report back)."""
        await self._coordinator.config_entry.runtime_data.client.set_solix_light(
            self._sn, on=True
        )
        self._on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **_: Any) -> None:
        """Turn the ambient light off (assumed state; device doesn't report back)."""
        await self._coordinator.config_entry.runtime_data.client.set_solix_light(
            self._sn, on=False
        )
        self._on = False
        self.async_write_ha_state()


class EufySdkSwitch(EufySdkPropertyEntity, SwitchEntity):
    """A writable boolean property as a switch."""

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Put a setting toggle under Configuration; leave a primary control up top."""
        super().__init__(coordinator, sn, spec)
        if is_setting(self._prop):
            self._attr_entity_category = EntityCategory.CONFIG

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
        self._attr_entity_category = EntityCategory.CONFIG

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
