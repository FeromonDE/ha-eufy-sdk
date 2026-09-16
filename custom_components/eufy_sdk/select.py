"""Select platform — one select per writable enum property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import EufySdkPropertyEntity, classify

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

# Solarbank display screen-off timeout: the app's dropdown, mapped to `screen_off_time`
# seconds. Unit confirmed in libapp.so (`_describeScreenOffSeconds`). "Never"
# (always-on) is a device-defined sentinel that is NOT hard-coded here: it is learned
# from a readback while the device is in that mode (see EufySolixScreenOffSelect), so
# no value is guessed.
SCREEN_OFF_NEVER = "Never"
SCREEN_OFF_OPTIONS: dict[str, int] = {
    "10s": 10,
    "20s": 20,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "30m": 1800,
}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EufySdkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a select for every writable enum property, plus Solix display selects."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = [
        EufySdkSelect(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if classify(spec) == "select"
    ]
    # Anker Solix: Solarbank display screen-off timeout + minimum SOC.
    solix = getattr(coordinator, "solix_devices", {}) or {}
    for sn, dev in solix.items():
        if "battery" in dev.get("capabilities", []):
            entities.append(EufySolixScreenOffSelect(coordinator, sn))
            entities.append(EufySolixMinSocSelect(coordinator, sn))
    async_add_entities(entities)


class EufySdkSelect(EufySdkPropertyEntity, SelectEntity):
    """A writable enum property as a select — options are the enum labels."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Build the raw<->label maps from the spec's enumValues."""
        super().__init__(coordinator, sn, spec)
        # enumValues is {raw: label}; JSON object keys arrive as strings.
        self._label_by_raw = {str(k): str(v) for k, v in spec["enumValues"].items()}
        self._raw_by_label = {v: k for k, v in self._label_by_raw.items()}
        self._attr_options = list(self._label_by_raw.values())

    @property
    def current_option(self) -> str | None:
        """The label for the property's current raw value."""
        v = self.prop_value
        return None if v is None else self._label_by_raw.get(str(v))

    async def async_select_option(self, option: str) -> None:
        """Write the raw value behind the chosen label."""
        raw = self._raw_by_label.get(option)
        if raw is None:
            return
        # Send an int when the raw code is numeric, else the raw string.
        value: int | str = int(raw) if raw.lstrip("-").isdigit() else raw
        await self.write(value)


class EufySolixScreenOffSelect(SelectEntity):
    """
    A Solarbank's display screen-off timeout (10s/20s/30s/1m/5m/30m/Never).

    Solix is a separate account/backend, so this is a standalone entity (not a
    coordinator/property one): it reads the live `screen_off_time` (seconds) via the
    bridge and writes the chosen option back. The timed options map 1:1 to seconds;
    "Never" (always-on) is a device sentinel that is NOT assumed — it is learned from a
    readback when the device is in that mode, then written back verbatim.
    """

    _attr_has_entity_name = True
    _attr_name = "Display Timeout"
    _attr_icon = "mdi:monitor-off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options: ClassVar[list[str]] = [*SCREEN_OFF_OPTIONS, SCREEN_OFF_NEVER]

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a Solix Solarbank; build its Anker Solix HA device_info."""
        self._coordinator = coordinator
        self._sn = sn
        self._seconds: int | None = None
        # The device's "Never" sentinel, learned from a readback (None until observed).
        self._never_value: int | None = None
        self._by_seconds = {v: k for k, v in SCREEN_OFF_OPTIONS.items()}
        dev = coordinator.solix_devices.get(sn, {})
        self._attr_unique_id = f"solix_{sn}_screen_off_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"solix:{sn}")},
            name=dev.get("name") or sn,
            manufacturer="Anker Solix",
            model=dev.get("productCode"),
            sw_version=dev.get("firmware"),
            serial_number=sn,
        )

    @property
    def available(self) -> bool:
        """Available while the bridge still lists this Solix device."""
        return self._sn in getattr(self._coordinator, "solix_devices", {})

    @property
    def current_option(self) -> str | None:
        """The label for the live screen_off_time (None until first read)."""
        if self._seconds is None:
            return None
        label = self._by_seconds.get(self._seconds)
        if label is not None:
            return label
        # An unrecognised value means the device is in its always-on mode — learn the
        # exact sentinel from this readback so we can write it back later.
        self._never_value = self._seconds
        return SCREEN_OFF_NEVER

    async def async_update(self) -> None:
        """Poll the live screen_off_time from the device."""
        client = self._coordinator.config_entry.runtime_data.client
        attrs = await client.get_solix_device_attrs(self._sn, ["screen_off_time"])
        raw = attrs.get("screen_off_time")
        if raw is not None:
            try:
                self._seconds = int(raw)
            except (TypeError, ValueError):
                self._seconds = None

    async def async_select_option(self, option: str) -> None:
        """Write the chosen timeout back (seconds, or the sentinel for Never)."""
        client = self._coordinator.config_entry.runtime_data.client
        if option == SCREEN_OFF_NEVER:
            if self._never_value is None:
                # No value guessed: we can only write "Never" once we've read what the
                # device uses for it. Ask the user to set it once in the Anker app.
                msg = (
                    "The 'Never' value has not been read from this device yet. "
                    "Set the display timeout to Never once in the Anker app, then HA "
                    "will learn it and this option will work."
                )
                raise HomeAssistantError(msg)
            seconds = self._never_value
        else:
            seconds = SCREEN_OFF_OPTIONS[option]
        await client.set_solix_screen_off_time(self._sn, seconds)
        self._seconds = seconds
        self.async_write_ha_state()


class EufySolixMinSocSelect(SelectEntity):
    """
    A Solarbank's minimum battery SOC (discharge cutoff), as a select.

    The options are NOT hard-coded: they come from the device's own preset list
    (`get_power_cutoff` -> each `output_cutoff_data` percent with its `id`). The label
    is the percent (e.g. "10%"); selecting one writes its `id` back. Solix is a separate
    account/backend, so this is a standalone (non-coordinator) entity that polls.
    """

    _attr_has_entity_name = True
    _attr_name = "Minimum Battery SOC"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a Solix Solarbank; build its Anker Solix HA device_info."""
        self._coordinator = coordinator
        self._sn = sn
        self._id_by_label: dict[str, int] = {}
        self._current: str | None = None
        self._attr_options = []
        dev = coordinator.solix_devices.get(sn, {})
        self._attr_unique_id = f"solix_{sn}_min_soc"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"solix:{sn}")},
            name=dev.get("name") or sn,
            manufacturer="Anker Solix",
            model=dev.get("productCode"),
            sw_version=dev.get("firmware"),
            serial_number=sn,
        )

    @property
    def available(self) -> bool:
        """Available while the bridge still lists this Solix device."""
        return self._sn in getattr(self._coordinator, "solix_devices", {})

    @property
    def current_option(self) -> str | None:
        """The label of the currently selected cutoff preset."""
        return self._current

    async def async_update(self) -> None:
        """Poll the device's cutoff presets and which one is selected."""
        client = self._coordinator.config_entry.runtime_data.client
        options = await client.get_solix_power_cutoff(self._sn)
        id_by_label: dict[str, int] = {}
        current: str | None = None
        for opt in options:
            pct = opt.get("output_cutoff_data")
            oid = opt.get("id")
            if pct is None or oid is None:
                continue
            label = f"{int(pct)}%"
            id_by_label[label] = int(oid)
            if opt.get("is_selected"):
                current = label
        if id_by_label:
            self._id_by_label = id_by_label
            self._attr_options = list(id_by_label)
            self._current = current

    async def async_select_option(self, option: str) -> None:
        """Write the chosen cutoff preset back by its device id."""
        cutoff_id = self._id_by_label.get(option)
        if cutoff_id is None:
            msg = f"unknown minimum-SOC option: {option}"
            raise HomeAssistantError(msg)
        client = self._coordinator.config_entry.runtime_data.client
        await client.set_solix_power_cutoff(self._sn, cutoff_id)
        self._current = option
        self.async_write_ha_state()
