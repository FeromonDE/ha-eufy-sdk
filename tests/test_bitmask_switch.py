"""Regression tests for bitfield switch writes."""

# ruff: noqa: INP001, S101, SLF001

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.eufy_sdk.switch import EufyBitmaskSwitch

FALLBACK_BASE = 0x30000


class TestEufyBitmaskSwitch(IsolatedAsyncioTestCase):
    """Verify that bitfield writes preserve the device's actual mask."""

    def _entity(
        self,
        value: float | str | None,
    ) -> EufyBitmaskSwitch:
        entity = EufyBitmaskSwitch.__new__(EufyBitmaskSwitch)
        entity._sn = "camera"
        entity._prop = "aiDetectType"
        entity._bit = 0x4
        entity._base = FALLBACK_BASE
        entity._assumed_value = None
        entity.coordinator = Mock(
            data={
                "camera": {
                    "state": {
                        "aiDetectType": value,
                    }
                }
            }
        )
        entity.write = AsyncMock()
        return entity

    def test_mask_uses_reported_numeric_state(self) -> None:
        """Use zero, high bits and numeric coercion without injecting the fallback."""
        for reported, expected in (
            (0, 0),
            (0x8007, 0x8007),
            (float(0x8007), 0x8007),
        ):
            with self.subTest(reported=reported):
                assert self._entity(reported)._mask() == expected

    def test_mask_falls_back_for_absent_state(self) -> None:
        """Absent state uses the configured fallback base."""
        assert self._entity(None)._mask() == FALLBACK_BASE

    def test_a_numeric_string_is_the_mask_for_both_read_and_write(self) -> None:
        """is_on and the write agree on a mask reported as a numeric string."""
        entity = self._entity("32775")
        assert entity._mask() == int("32775")
        assert entity.is_on is True

    async def test_a_json_value_reads_unknown_and_is_not_overwritten(self) -> None:
        """A JSON-shaped report doesn't crash setup or get replaced by a number."""
        entity = self._entity(
            '{"ai_detect_type":196623,"ai_switch":1,"ai_use_global":1,'
            '"ai_notification":2147483648,"channel":0}'
        )
        assert entity.is_on is None
        with pytest.raises(HomeAssistantError):
            await entity.async_turn_on()
        entity.write.assert_not_awaited()

    async def test_write_preserves_device_specific_bits(self) -> None:
        """Change only the requested bit using real coordinator state."""
        entity = self._entity(0x8007)

        await entity.async_turn_off()
        entity.write.assert_awaited_once_with(0x8003)

        entity.write.reset_mock()
        entity.coordinator.data["camera"]["state"]["aiDetectType"] = 0x8003

        await entity.async_turn_on()
        entity.write.assert_awaited_once_with(0x8007)

    async def test_zero_mask_does_not_inject_fallback_base(self) -> None:
        """A reported zero is authoritative rather than a missing value."""
        entity = self._entity(0)

        await entity.async_turn_on()

        entity.write.assert_awaited_once_with(0x4)
