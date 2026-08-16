"""
How SDK push-event names map onto HA entities (real-time, not the slow poll).

The bridge forwards semantic events (motion / personDetected / doorbellPress / …) from
the SDK's always-on push channel onto the HA bus as `<DOMAIN>_event`. These maps decide
which become auto-off binary_sensors vs. event-entity fires, and gate each on the
device's capabilities so a device only gets entities for events it can emit.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

# Push events surfaced as auto-off binary_sensors.
# bus event name -> (key, friendly name, device_class, required capability)
PUSH_BINARY_SENSORS: dict[str, tuple[str, str, BinarySensorDeviceClass, str]] = {
    "motion": ("motion", "Motion", BinarySensorDeviceClass.MOTION, "motion"),
    "personDetected": (
        "person",
        "Person",
        BinarySensorDeviceClass.OCCUPANCY,
        "person_detection",
    ),
}

# Discrete push events surfaced on a per-device "Detection" event entity.
# bus event name -> HA event_type
DETECTION_EVENTS: dict[str, str] = {
    "petDetection": "pet",
    "vehicleDetected": "vehicle",
    "strangerDetected": "stranger",
    "soundDetected": "sound",
    "cryingDetected": "crying",
    "packageDelivered": "package_delivered",
    "packageTaken": "package_taken",
    "packageStranded": "package_stranded",
}

# A doorbell press is its own event entity (device_class DOORBELL).
DOORBELL_EVENT = "doorbellPress"
DOORBELL_EVENT_TYPE = "pressed"

# Capabilities that make a device eligible for a Detection event entity.
DETECTION_CAPABILITIES = frozenset({"motion", "person_detection", "doorbell"})

# Push carries no "cleared" signal, so a push binary_sensor auto-offs after this delay.
PUSH_AUTO_OFF_SECONDS = 30
