# ruff: noqa: ANN201, D100, D101, D102, INP001, PT009, S101

import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).parents[1] / "custom_components/eufy_sdk/alarm_logic.py"
_SPEC = importlib.util.spec_from_file_location("alarm_logic_custom", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class CustomAlarmLabelTests(unittest.TestCase):
    def test_custom_alarm_states_use_configured_display_names(self):
        names = ("Sleep", "Night", "Vacation")
        self.assertEqual(
            _MODULE.display_alarm_state(_MODULE.AlarmState.ARMED_CUSTOM_BYPASS, names),
            "Sleep",
        )
        self.assertEqual(
            _MODULE.display_alarm_state(_MODULE.AlarmState.ARMED_NIGHT, names),
            "Night",
        )
        self.assertEqual(
            _MODULE.display_alarm_state(_MODULE.AlarmState.ARMED_VACATION, names),
            "Vacation",
        )
        self.assertEqual(
            _MODULE.display_alarm_state(_MODULE.AlarmState.TRIGGERED, names),
            _MODULE.AlarmState.TRIGGERED,
        )


if __name__ == "__main__":
    unittest.main()
