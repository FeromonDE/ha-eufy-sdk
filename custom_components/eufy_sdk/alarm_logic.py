"""Explicit Eufy HomeBase to Home Assistant alarm mappings."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class AlarmState(StrEnum):
    """HA alarm states used by the verified Eufy modes."""

    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_CUSTOM_BYPASS = "armed_custom_bypass"
    ARMED_NIGHT = "armed_night"
    ARMED_VACATION = "armed_vacation"


MODE_AWAY = 0
MODE_HOME = 1
MODE_CUSTOM_1 = 3
MODE_CUSTOM_2 = 4
MODE_CUSTOM_3 = 5
MODE_DISARMED = 63

# The upstream SDK currently accepts writes only for the three wire-captured modes.
# Custom/schedule/off/geofence remain readable but must not be offered as writable controls.
SETTABLE_ARMING_MODES = frozenset({MODE_AWAY, MODE_HOME, MODE_DISARMED})

# Custom 1/2/3 retain the established old-integration compatibility mapping.
RAW_TO_ALARM_STATE = {
    MODE_AWAY: AlarmState.ARMED_AWAY,
    MODE_HOME: AlarmState.ARMED_HOME,
    MODE_CUSTOM_1: AlarmState.ARMED_CUSTOM_BYPASS,
    MODE_CUSTOM_2: AlarmState.ARMED_NIGHT,
    MODE_CUSTOM_3: AlarmState.ARMED_VACATION,
    MODE_DISARMED: AlarmState.DISARMED,
}


def alarm_state_for_raw(raw: Any) -> AlarmState | None:
    """Map only explicitly supported Eufy modes."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw)
        except ValueError:
            return None
    else:
        return None
    return RAW_TO_ALARM_STATE.get(value)


def display_alarm_state_for_raw(
    raw: Any,
    custom_names: tuple[str, str, str],
) -> AlarmState | str | None:
    """Return the HA state, substituting user labels for Eufy custom modes 1/2/3."""
    state = alarm_state_for_raw(raw)
    if state == AlarmState.ARMED_CUSTOM_BYPASS:
        return custom_names[0]
    if state == AlarmState.ARMED_NIGHT:
        return custom_names[1]
    if state == AlarmState.ARMED_VACATION:
        return custom_names[2]
    return state
