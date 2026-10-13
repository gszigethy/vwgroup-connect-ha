"""Companion controls leave Configuration without changing cloud categories."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import EntityCategory

from custom_components.vag_connect.number import NUMBER_DESCRIPTIONS, VagConnectNumber
from custom_components.vag_connect.switch import (
    COMPANION_CLIMATE_SETTINGS,
    VagCompanionClimateSettingSwitch,
)


@pytest.mark.parametrize("companion", [True, False], ids=["companion", "cloud"])
def test_charge_target_category(companion: bool) -> None:
    coordinator = MagicMock()
    coordinator.is_companion.return_value = companion
    description = next(d for d in NUMBER_DESCRIPTIONS if d.key == "target_soc")
    entity = VagConnectNumber(coordinator, "VIN1", description)

    assert entity.entity_category is (None if companion else EntityCategory.CONFIG)
    assert description.entity_category is EntityCategory.CONFIG


@pytest.mark.parametrize("key,field,command_id,icon", COMPANION_CLIMATE_SETTINGS)
def test_climate_setting_category(key: str, field: str, command_id: str, icon: str) -> None:
    coordinator = MagicMock()
    coordinator.is_companion.return_value = True
    entity = VagCompanionClimateSettingSwitch(
        coordinator, "VIN1", key, field, command_id, icon,
    )

    expected = (
        None if key in {"window_heating_auto_switch", "climate_at_unlock_switch"}
        else EntityCategory.CONFIG
    )
    assert entity.entity_category is expected
