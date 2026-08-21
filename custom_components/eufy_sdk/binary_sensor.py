"""Binary sensor platform — one per read-only boolean property (motion, contact, …)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .entity import EufySdkDeviceEntity, EufySdkPropertyEntity, classify
from .pushmap import PUSH_AUTO_OFF_SECONDS, PUSH_BINARY_SENSORS

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import EufySdkDataUpdateCoordinator
    from .data import EufySdkConfigEntry

EVENT_TYPE = f"{DOMAIN}_event"

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
    """Create a binary sensor per read-only bool property, plus push-driven ones."""
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = [
        EufySdkBinarySensor(coordinator, sn, spec)
        for sn in coordinator.data
        for spec in entry.runtime_data.properties.get(sn, [])
        if classify(spec) == "binary_sensor"
    ]
    # Push-driven detections (motion / person): flipped ON in real time by the SDK's
    # push channel, then auto-OFF (push has no "cleared" signal). Gated on capability.
    for sn, dev in coordinator.data.items():
        caps = set(dev.get("capabilities", []))
        for bus_event, (key, name, device_class, cap) in PUSH_BINARY_SENSORS.items():
            if cap in caps:
                entities.append(
                    EufyPushBinarySensor(
                        coordinator, sn, bus_event, (key, name, device_class)
                    )
                )
    # A "Streaming" sensor per camera: ON while the bridge holds a live P2P feed
    # (go2rtc pulling /stream). Edge-driven by the bridge's `streamState` event,
    # with the device-list poll as the initial/reconnect value.
    entities.extend(
        EufyStreamingBinarySensor(coordinator, sn)
        for sn, dev in coordinator.data.items()
        if dev.get("stream")
    )
    async_add_entities(entities)


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


class EufyPushBinarySensor(EufySdkDeviceEntity, BinarySensorEntity):
    """A detection driven by push events: ON on the event, auto-OFF after a delay."""

    _attr_is_on = False

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        bus_event: str,
        spec: tuple[str, str, BinarySensorDeviceClass],
    ) -> None:
        """Bind to one push event name (e.g. 'motion') for this device."""
        super().__init__(coordinator, sn)
        key, name, device_class = spec
        self._bus_event = bus_event
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._cancel_off = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to the bus and cancel any pending auto-off on removal."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_TYPE, self._handle_event))
        self.async_on_remove(self._cancel_timer)

    @callback
    def _cancel_timer(self) -> None:
        """Cancel a pending auto-off timer, if any."""
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None

    @callback
    def _handle_event(self, event: Event) -> None:
        """Turn ON for this device's matching push event and (re)arm the auto-off."""
        data = event.data
        if data.get("deviceSn") != self._sn or data.get("event") != self._bus_event:
            return
        self._attr_is_on = True
        self._cancel_timer()
        self._cancel_off = async_call_later(
            self.hass, PUSH_AUTO_OFF_SECONDS, self._auto_off
        )
        self.async_write_ha_state()

    @callback
    def _auto_off(self, _now: object) -> None:
        """Clear the detection once the auto-off delay elapses."""
        self._cancel_off = None
        self._attr_is_on = False
        self.async_write_ha_state()


class EufyStreamingBinarySensor(EufySdkDeviceEntity, BinarySensorEntity):
    """ON while a live P2P feed is active (the camera is being streamed)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_name = "Streaming"

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
    ) -> None:
        """Bind to a camera serial; start from the device-list value pre-event."""
        super().__init__(coordinator, sn)
        self._attr_unique_id = f"{sn}_streaming"
        self._active: bool | None = (
            None  # last streamState event; None → fall back to the poll
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to the bridge's streamState events for this device."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_TYPE, self._handle_event))

    @callback
    def _handle_event(self, event: Event) -> None:
        """Flip on/off from this device's streamState event (both edges)."""
        data = event.data
        if data.get("deviceSn") != self._sn or data.get("event") != "streamState":
            return
        self._active = bool(data.get("active"))
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Event value once seen; else the device-list `streaming` flag."""
        if self._active is not None:
            return self._active
        return bool(self.device.get("streaming"))
