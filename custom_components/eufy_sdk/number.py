"""Number platform — one number per writable numeric property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import EufySdkPropertyEntity, classify, has_capability
from .light import LIGHT_OWNED_PROPS

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

EVENT_TYPE = f"{DOMAIN}_event"

# The manifest carries no min/max, so pick a sane range from the value's `kind`.
_RANGE_BY_KIND = {"percent": (0, 100), "seconds": (0, 86400), "degrees": (0, 360)}
_DEFAULT_RANGE = (0, 65535)
# Kinds with a small, bounded range read better as a slider than a text box.
_SLIDER_KINDS = {"percent", "degrees"}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create numbers for writable properties, plus Solix SOC-limit sliders."""
    coordinator = entry.runtime_data.coordinator
    entities: list[NumberEntity] = [
        EufySdkNumber(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if classify(spec) == "number"
        # The light platform owns lightBrightness for smart_light (see switch.py).
        and not (
            spec["name"] in LIGHT_OWNED_PROPS
            and has_capability(coordinator.data[sn], "smart_light")
        )
    ]

    # Anker Solix (separate account): a Solarbank's discharge/charge limits as sliders.
    # These write the cloud SOC block (param_type 27) and reflect live `b5` telemetry.
    solix = getattr(coordinator, "solix_devices", {}) or {}
    for sn, dev in solix.items():
        if "battery" in dev.get("capabilities", []):
            entities.append(EufySolixSocLimitNumber(coordinator, sn, SOC_DISCHARGE))
            entities.append(EufySolixSocLimitNumber(coordinator, sn, SOC_CHARGE))

    async_add_entities(entities)


class EufySdkNumber(EufySdkPropertyEntity, NumberEntity):
    """A writable numeric property as a number."""

    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Set unit, a range from the value's kind, and slider-vs-box mode."""
        super().__init__(coordinator, sn, spec)
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        kind = spec.get("kind")
        low, high = _RANGE_BY_KIND.get(kind, _DEFAULT_RANGE)
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        # A percentage (brightness, volume) is a slider; open-ended values a box.
        self._attr_mode = NumberMode.SLIDER if kind in _SLIDER_KINDS else NumberMode.BOX

    @property
    def native_value(self) -> float | None:
        """The property's current numeric value."""
        v = self.prop_value
        return float(v) if isinstance(v, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Write the value (as an int when it's whole, to match the wire)."""
        await self.write(int(value) if value == int(value) else value)


class _SocLimit(NamedTuple):
    """
    A Solix SOC-limit slider descriptor.

    `key` is the telemetry value key; `write_kw` the api.py write keyword. Discharge =
    minimum SOC (floor); charge = maximum SOC (ceiling).
    """

    key: str
    name: str
    icon: str
    low: int
    high: int
    write_kw: str


# `dischargeLimit` / `chargeLimit` are the b5-blob telemetry keys the SDK decodes and
# the bridge broadcasts (also echoed right after a write). Bounds keep them from
# crossing; the device still validates. Min SOC realistically sits low, max SOC high.
SOC_DISCHARGE = _SocLimit(
    "dischargeLimit", "Discharge Limit", "mdi:battery-arrow-down", 0, 20, "discharge"
)
SOC_CHARGE = _SocLimit(
    "chargeLimit", "Charge Limit", "mdi:battery-arrow-up", 80, 100, "charge"
)


class EufySolixSocLimitNumber(NumberEntity):
    """
    A Solarbank battery discharge/charge limit as a slider — reflects the DEVICE state.

    Setting it issues an `algo_ecdh` cloud write (`set_site_device_param`, param_type
    27) through the bridge, which is read-modify-write so the sibling limit and backup
    reserve are preserved. The shown value seeds from the bridge's `solix.devices`
    snapshot and updates on `solixReading` events carrying `dischargeLimit` /
    `chargeLimit` (decoded from the `b5` telemetry blob) — so a change made in the Anker
    app is reflected within ~seconds, and this is NOT assumed-state. A write we issue
    sets the value optimistically; the bridge echoes the merged result immediately and
    the next telemetry frame confirms. Device `solix:<sn>`, like the light/sensors.
    """

    _attr_has_entity_name = True
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        limit: _SocLimit,
    ) -> None:
        """Bind to a Solix Solarbank limit; seed from its telemetry snapshot."""
        self._coordinator = coordinator
        self._sn = sn
        self._limit = limit
        dev = coordinator.solix_devices.get(sn, {})
        self._value = self._read_snapshot(dev)
        self._attr_name = limit.name
        self._attr_icon = limit.icon
        self._attr_native_min_value = limit.low
        self._attr_native_max_value = limit.high
        self._attr_unique_id = f"solix_{sn}_{limit.write_kw}_limit"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"solix:{sn}")},
            name=dev.get("name") or sn,
            manufacturer="Anker Solix",
            model=dev.get("productCode"),
            sw_version=dev.get("firmware"),
            serial_number=sn,
        )

    def _read_snapshot(self, dev: dict[str, Any]) -> float | None:
        """Read this limit's percent from a device's values; None if absent."""
        v = (dev.get("values") or {}).get(self._limit.key)
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def native_value(self) -> float | None:
        """The limit's current value from telemetry (None until a reading arrives)."""
        return self._value

    @property
    def available(self) -> bool:
        """Available while the bridge still lists this Solix device."""
        return self._sn in getattr(self._coordinator, "solix_devices", {})

    async def async_added_to_hass(self) -> None:
        """Subscribe to live readings AND the coordinator's device snapshot."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_TYPE, self._handle_event))
        self.async_on_remove(
            self._coordinator.async_add_listener(self._refresh_from_snapshot)
        )
        self._refresh_from_snapshot()

    @callback
    def _refresh_from_snapshot(self) -> None:
        """Adopt the limit from the coordinator's Solix snapshot, if changed."""
        v = self._read_snapshot(self._coordinator.solix_devices.get(self._sn, {}))
        if v is not None and v != self._value:
            self._value = v
            self.async_write_ha_state()

    @callback
    def _handle_event(self, event: Event) -> None:
        """Update from a `solixReading` for this device carrying this limit's key."""
        data = event.data
        if data.get("event") != "solixReading" or data.get("deviceSn") != self._sn:
            return
        values = data.get("values") or {}
        if self._limit.key in values:
            self._value = float(values[self._limit.key])
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Write the limit (whole-percent; optimistic — the bridge echo confirms)."""
        await self._coordinator.config_entry.runtime_data.client.set_solix_soc_limits(
            self._sn, **{self._limit.write_kw: int(value)}
        )
        self._value = float(int(value))
        self.async_write_ha_state()
