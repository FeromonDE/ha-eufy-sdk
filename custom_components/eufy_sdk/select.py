"""Select platform — one select per writable enum property."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import EufySdkPropertyEntity, classify

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

EVENT_TYPE = f"{DOMAIN}_event"

# Solarbank display screen-off timeout — set by an MQTT command (cmd 17, ff09 msgtype
# 0x68, tag a5=[01,index]), live-captured + write-verified on an AE103. The value is a
# 1-based index into the app dropdown. "Never" is a SEPARATE command (an HTTP
# low-brightness mode, not yet reversed), so it's omitted. It's not in telemetry/HTTP
# (get_device_attrs {}, no scene field, no ff09 tag), BUT an app change publishes that
# a5 command on the device /req topic, which the bridge co-subscribes to — so the SDK
# emits `displayTimeoutIndex` and this select reflects an app change.
# 1-based dropdown index → a5=[01,index] MQTT /req command (30s/5m live-captured as
# a5=01 03 / 01 05 — an MQTT write, not HTTP). "Never" = index 0 (from the app's picker
# option list). ONE ASYMMETRY: setting Never IN THE APP uses a separate non-a5 path we
# can't see, so an app→Never change won't reflect in HA (it stays on the last value);
# HA→Never and every timed change both ways do work.
DISPLAY_TIMEOUT_INDEX: dict[str, int] = {
    "10s": 1,
    "20s": 2,
    "30s": 3,
    "1m": 4,
    "5m": 5,
    "30m": 6,
    "Never": 0,
}
DISPLAY_TIMEOUT_LABEL: dict[int, str] = {v: k for k, v in DISPLAY_TIMEOUT_INDEX.items()}


async def async_setup_entry(
    hass: HomeAssistant,
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
    # Anker Solix: Solarbank display screen-off timeout. (The minimum-SOC / discharge
    # cutoff is now the Discharge Limit slider on the number platform.)
    solix = getattr(coordinator, "solix_devices", {}) or {}
    for sn, dev in solix.items():
        if "battery" in dev.get("capabilities", []):
            entities.append(EufySolixScreenOffSelect(coordinator, sn))
            # Retire the old "Minimum Battery SOC" select (superseded by the Discharge
            # Limit slider) so it doesn't linger as an unavailable entity after upgrade.
            _remove_stale_min_soc(hass, sn)
    async_add_entities(entities)


@callback
def _remove_stale_min_soc(hass: HomeAssistant, sn: str) -> None:
    """Drop the retired `solix_<sn>_min_soc` select from the registry, if present."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("select", DOMAIN, f"solix_{sn}_min_soc")
    if entity_id:
        registry.async_remove(entity_id)


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

    Solix is a separate account/backend, so this is a standalone entity. The timeout is
    set by an MQTT `…/req` command carrying a 1-based dropdown index (Never = 0) — not
    an HTTP write (live-captured: 30s=a5:03, 5m=a5:05). It isn't in any HTTP read or
    passive telemetry frame, but an app change publishes that command on the `/req`
    topic, which the bridge co-subscribes to — the SDK surfaces it as
    `displayTimeoutIndex`, so this select reflects an app change live (snapshot +
    `solixReading` events). A value we set is shown optimistically.

    Two honest limitations (no code can fix without more reversing): (1) there is NO
    readable seed for the current value, so on restart it is unknown until the next
    change rather than showing a possibly-stale guess. (2) Setting "Never" IN THE APP
    uses a separate non-a5 path we can't see, so an app→Never change won't reflect here
    (it holds the last value); HA→Never (the a5=0 write) and every timed change both
    ways do work.
    """

    _attr_has_entity_name = True
    _attr_name = "Display Timeout"
    _attr_icon = "mdi:monitor-off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_options: ClassVar[list[str]] = list(DISPLAY_TIMEOUT_INDEX)

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a Solix Solarbank; seed the current index from telemetry."""
        self._coordinator = coordinator
        self._sn = sn
        dev = coordinator.solix_devices.get(sn, {})
        self._current = self._label_from(dev)
        self._attr_unique_id = f"solix_{sn}_screen_off_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"solix:{sn}")},
            name=dev.get("name") or sn,
            manufacturer="Anker Solix",
            model=dev.get("productCode"),
            sw_version=dev.get("firmware"),
            serial_number=sn,
        )

    @staticmethod
    def _label_from(dev: dict[str, Any]) -> str | None:
        """Map a device's `displayTimeoutIndex` to a dropdown label, if present."""
        idx = (dev.get("values") or {}).get("displayTimeoutIndex")
        return None if idx is None else DISPLAY_TIMEOUT_LABEL.get(int(idx))

    @property
    def available(self) -> bool:
        """Available while the bridge still lists this Solix device."""
        return self._sn in getattr(self._coordinator, "solix_devices", {})

    @property
    def current_option(self) -> str | None:
        """The selected timeout (from the app's command or the last value we set)."""
        return self._current

    async def async_added_to_hass(self) -> None:
        """Reflect an app timeout change: live events + the coordinator snapshot."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_TYPE, self._handle_event))
        self.async_on_remove(
            self._coordinator.async_add_listener(self._refresh_from_snapshot)
        )
        self._refresh_from_snapshot()

    @callback
    def _refresh_from_snapshot(self) -> None:
        """Adopt the index from the coordinator's Solix snapshot, if changed."""
        label = self._label_from(self._coordinator.solix_devices.get(self._sn, {}))
        if label is not None and label != self._current:
            self._current = label
            self.async_write_ha_state()

    @callback
    def _handle_event(self, event: Event) -> None:
        """Update from a `solixReading` for this device carrying displayTimeoutIndex."""
        data = event.data
        if data.get("event") != "solixReading" or data.get("deviceSn") != self._sn:
            return
        idx = (data.get("values") or {}).get("displayTimeoutIndex")
        if idx is not None:
            label = DISPLAY_TIMEOUT_LABEL.get(int(idx))
            if label is not None and label != self._current:
                self._current = label
                self.async_write_ha_state()

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
