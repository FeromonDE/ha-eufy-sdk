# ruff: noqa: ANN201, D100, D101, D102, INP001, PT009

import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import custom_components.eufy_sdk as integration
from custom_components.eufy_sdk.const import CONF_HOST, CONF_PORT


class SetupEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_valueless_arming_event_refreshes_known_device_only(self):
        hass = Mock()
        hass.bus.async_fire = Mock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()

        entry = Mock()
        entry.data = {CONF_HOST: "bridge", CONF_PORT: 3000}
        entry.options = {}
        entry.domain = "eufy_sdk"
        entry.entry_id = "test-entry"
        entry.add_update_listener = Mock(return_value=lambda: None)
        entry.async_on_unload = Mock()
        scheduled = []
        entry.async_create_background_task = Mock(
            side_effect=lambda _hass, coroutine, _name: scheduled.append(coroutine)
        )

        coordinator = Mock(data={"homebase": {"state": {"armingMode": 1}}})
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        client = Mock()
        client.set_poll_ms = AsyncMock()
        client.get_properties = AsyncMock(return_value=[])
        client.get_device = AsyncMock(
            return_value={"sn": "homebase", "state": {"armingMode": 4}}
        )
        callbacks = []

        def make_client(**kwargs: Any) -> Mock:
            callbacks.append(kwargs["on_event"])
            return client

        with (
            patch.object(
                integration, "EufySdkDataUpdateCoordinator", return_value=coordinator
            ),
            patch.object(integration, "EufySdkApiClient", side_effect=make_client),
            patch.object(integration, "async_get_clientsession", return_value=Mock()),
            patch.object(
                integration, "async_get_loaded_integration", return_value=Mock()
            ),
        ):
            await integration.async_setup_entry(hass, entry)
            self.assertEqual(len(callbacks), 1)

        callbacks[0]({"event": "armingModeChanged", "deviceSn": "homebase"})
        self.assertEqual(len(scheduled), 1)
        await scheduled.pop()
        client.get_device.assert_awaited_once_with("homebase")
        self.assertEqual(coordinator.data["homebase"]["state"]["armingMode"], 4)
        coordinator.async_update_listeners.assert_called_once_with()
        coordinator.async_request_refresh.assert_not_awaited()

        callbacks[0]({"event": "armingModeChanged", "deviceSn": "unknown"})
        self.assertEqual(scheduled, [])


if __name__ == "__main__":
    unittest.main()
