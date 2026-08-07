"""Base entity for eufy_sdk — one HA device per eufy device (keyed by serial)."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import EufySdkDataUpdateCoordinator


class EufySdkDeviceEntity(CoordinatorEntity[EufySdkDataUpdateCoordinator]):
    """An entity attached to one eufy device (`sn`), from the bridge device list."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: EufySdkDataUpdateCoordinator, sn: str) -> None:
        """Bind to a device serial and build its HA device_info."""
        super().__init__(coordinator)
        self._sn = sn
        dev = coordinator.data.get(sn, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name=dev.get("name") or sn,  # the user's device name (e.g. "Dining room")
            manufacturer="eufy",
            model=dev.get("model") or dev.get("codec"),  # the model code, not the codec
            serial_number=sn,
        )

    @property
    def device(self) -> dict:
        """Return the latest device record (sn/name/codec/capabilities/stream)."""
        return self.coordinator.data.get(self._sn, {})

    @property
    def available(self) -> bool:
        """Available while the bridge still reports this device."""
        return super().available and self._sn in self.coordinator.data


def label_for(prop: str) -> str:
    """Turn a camelCase name into a human label ('statusLed' -> 'Status Led')."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", prop)
    return spaced[:1].upper() + spaced[1:]


def classify(spec: dict[str, Any]) -> str | None:
    """
    Route one property spec to exactly one platform, so no two platforms claim it.

    A `kind: "bitfield"` (e.g. `aiDetectType`) is never a scalar you'd nudge — it's a
    pack of bits — so it routes to "bitfield" for bespoke handling (see bespoke.py):
    known ones become per-bit switches, unknown ones a read-only sensor.

    A writable number is only a `number` when it has a real scale (`kind` other than
    bitfield, or a `unit`) — a bounded quantity you'd adjust (brightness %, a timer).
    Otherwise it's an opaque code and becomes a read-only sensor, as does a writable
    enum with no options to choose from.
    """
    t, writable, kind = spec.get("type"), spec.get("writable"), spec.get("kind")
    if kind == "bitfield":
        return "bitfield"
    has_scale = bool(kind or spec.get("unit"))
    if t == "bool":
        return "switch" if writable else "binary_sensor"
    if t == "enum":
        return "select" if (writable and spec.get("enumValues")) else "sensor"
    if t == "number":
        return "number" if (writable and has_scale) else "sensor"
    if t == "string":
        return "sensor"
    return None


class EufySdkPropertyEntity(EufySdkDeviceEntity):
    """An entity bound to one property, reading its live value from the `state` map."""

    def __init__(
        self,
        coordinator: EufySdkDataUpdateCoordinator,
        sn: str,
        spec: dict[str, Any],
    ) -> None:
        """Bind to a property spec ({name, type, unit, kind, writable, enumValues})."""
        super().__init__(coordinator, sn)
        self._spec = spec
        self._prop: str = spec["name"]
        self._attr_unique_id = f"{sn}_{self._prop}"
        self._attr_name = label_for(self._prop)

    @property
    def prop_value(self) -> Any:
        """The property's current value from the device's live `state` map."""
        return self.device.get("state", {}).get(self._prop)

    async def write(self, value: Any) -> None:
        """Write the property back through the bridge, then refresh."""
        client = self.coordinator.config_entry.runtime_data.client
        await client.set_property(self._sn, self._prop, value)
        await self.coordinator.async_request_refresh()
