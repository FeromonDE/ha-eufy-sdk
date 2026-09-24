# ruff: noqa: ANN201, D100, D101, D102, INP001, PT009, S101

import importlib.util
import unittest
from pathlib import Path

from homeassistant.components.event import DoorbellEventType

_MODULE_PATH = Path(__file__).parents[1] / "custom_components/eufy_sdk/pushmap.py"
_SPEC = importlib.util.spec_from_file_location("pushmap", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class DoorbellEventTypeTests(unittest.TestCase):
    def test_doorbell_uses_home_assistant_standard_ring_event(self):
        self.assertEqual(_MODULE.DOORBELL_EVENT_TYPE, DoorbellEventType.RING)


if __name__ == "__main__":
    unittest.main()
