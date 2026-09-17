"""Select platform — one select per writable enum property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import EufySdkPropertyEntity, classify

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

# Solarbank display screen-off timeout — set by an MQTT command (cmd 17, ff09 msgtype
# 0x68, tag a5=[01,index]), live-captured + write-verified on an AE103. The value is a
# 1-based index into the app dropdown. "Never" is a SEPARATE command (an HTTP
# low-brightness mode, not yet reversed), so it's omitted. Unlike the ambient light
# (readable from ff09 tag 0xba), the current timeout is NOT exposed anywhere: confirmed
# by a live sweep of all four very-different indices — get_device_attrs stays {}, the
# scene carries no timeout field, and NO ff09 tag moved. So HA cannot know what the app
# set it to; this select is unavoidably OPTIMISTIC (it shows only what HA itself set).
DISPLAY_TIMEOUT_INDEX: dict[str, int] = {
    "10s": 1,
    "20s": 2,
    "30s": 3,
    "1m": 4,
    "5m": 5,
    "30m": 6,
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
    A Solarbank's display screen-off timeout (10s/20s/30s/1m/5m/30m).

    Solix is a separate account/backend, so this is a standalone entity. The timeout is
    set by an MQTT command (write-verified live) carrying a 1-based dropdown index.
    The current value is not exposed by the cloud, so the select is OPTIMISTIC: it shows
    the value it last set (`None` until picked). "Never" is separate, omitted here.
    """

    _attr_has_entity_name = True
    _attr_name = "Display Timeout"
    _attr_icon = "mdi:monitor-off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_options: ClassVar[list[str]] = list(DISPLAY_TIMEOUT_INDEX)

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a Solix Solarbank; build its Anker Solix HA device_info."""
        self._coordinator = coordinator
        self._sn = sn
        self._current: str | None = None
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
        """The last value we set (optimistic; the device doesn't report it)."""
        return self._current

    async def async_select_option(self, option: str) -> None:
        """Send the chosen timeout as its 1-based index via the bridge MQTT command."""
        index = DISPLAY_TIMEOUT_INDEX.get(option)
        if index is None:
            msg = f"unknown display timeout: {option}"
            raise HomeAssistantError(msg)
        client = self._coordinator.config_entry.runtime_data.client
        await client.set_solix_display_timeout(self._sn, index)
        self._current = option
        self.async_write_ha_state()


class EufySolixMinSocSelect(SelectEntity):
    """
    A Solarbank's minimum battery SOC (discharge cutoff), as a select.

    The options are NOT hard-coded: they come from the device's own preset list
    (`get_power_cutoff` — each `output_cutoff_data` percent, its `id`, and which is
    `is_selected`). The label is the percent (e.g. "10%"); selecting one writes its `id`
    back. The selection is read back from the device, so a change made outside HA (the
    app) IS reflected: rather than relying on HA's implicit entity polling (which proved
    unreliable for these standalone Solix entities), the refresh is driven off the
    coordinator's own update cycle — the trigger the Solix sensors use — so it re-reads
    every poll interval. Solix is a separate account/backend (standalone entity).
    """

    _attr_has_entity_name = True
    _attr_name = "Minimum Battery SOC"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False  # driven off the coordinator cycle

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

    async def async_added_to_hass(self) -> None:
        """Read once now, then refresh on every coordinator update cycle."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self._schedule_refresh)
        )
        await self._refresh()

    @callback
    def _schedule_refresh(self) -> None:
        """Coordinator ticked — re-read the cutoff selection off the event loop."""
        self.hass.async_create_task(self._refresh())

    async def _refresh(self) -> None:
        """Poll the cutoff presets + selection; write state if it changed."""
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
        if id_by_label and (
            id_by_label != self._id_by_label or current != self._current
        ):
            self._id_by_label = id_by_label
            self._attr_options = list(id_by_label)
            self._current = current
            self.async_write_ha_state()

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
