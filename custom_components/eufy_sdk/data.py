"""Custom types for eufy_sdk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import EufySdkApiClient
    from .coordinator import EufySdkDataUpdateCoordinator


type EufySdkConfigEntry = ConfigEntry[EufySdkData]


@dataclass
class EufySdkData:
    """Data for the EufySdk integration."""

    client: EufySdkApiClient
    coordinator: EufySdkDataUpdateCoordinator
    integration: Integration
