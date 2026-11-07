# ruff: noqa: ANN201, D100, D101, D102, INP001, PT009, SLF001

import unittest

from homeassistant.components.event import DoorbellEventType

from custom_components.eufy_sdk.event import EufySdkDoorbellEvent


class DoorbellEventTypeTests(unittest.TestCase):
    def test_doorbell_uses_home_assistant_standard_ring_event(self):
        self.assertEqual(
            EufySdkDoorbellEvent._match(None, "doorbellPress"),
            DoorbellEventType.RING,
        )


if __name__ == "__main__":
    unittest.main()
