# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion climate Start: mode select + temperature number held in HA.

The 4.6.4 Air Conditioning sheet has no Save; Start applies the selected mode
and the dial. So both are HA-held values: changing them only stores them (no
phone or car traffic), they are restored across restarts, the poll never
overwrites them, and the temperature is unavailable in window heating only.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.vag_connect.companion.client import CompanionClient
from custom_components.vag_connect.number import (
    NUMBER_DESCRIPTIONS,
    VagCompanionClimateTemperatureNumber,
)
from custom_components.vag_connect.select import VagCompanionClimateModeSelect

VIN = "WVWZZZTESTVIN0001"
TEMP_DESC = next(d for d in NUMBER_DESCRIPTIONS if d.key == "target_temperature")


class _TrippedChannel:
    """Any phone access fails the test: storing must never reach the phone."""

    def __getattr__(self, name):  # pragma: no cover - must not run
        raise AssertionError(f"the channel was touched: {name}")


def _client() -> CompanionClient:
    client = CompanionClient.__new__(CompanionClient)
    client._brand = "volkswagen"
    client._channel = _TrippedChannel()
    return client


def _coordinator(client: CompanionClient, vehicle: dict | None = None):
    coord = MagicMock()
    coord.is_companion = MagicMock(return_value=True)
    coord._cariad_client = client
    coord.data = {VIN: dict(vehicle or {})}
    coord.last_update_success = True
    coord._cariad_cmd = AsyncMock(side_effect=AssertionError("no command on a store"))

    async def set_temp(vin, temp_c):
        # The real coordinator glue (companion branch), on this mock.
        from custom_components.vag_connect.coordinator import VagConnectCoordinator

        await VagConnectCoordinator.async_set_climatisation_temperature(coord, vin, temp_c)

    coord.async_set_climatisation_temperature = set_temp
    return coord


def _number(coord):
    n = VagCompanionClimateTemperatureNumber(coord, VIN, TEMP_DESC)
    n.async_write_ha_state = MagicMock()
    return n


def _select(coord):
    s = VagCompanionClimateModeSelect(coord, VIN)
    s.async_write_ha_state = MagicMock()
    return s


@pytest.mark.asyncio
async def test_changing_the_number_and_select_only_stores():
    client = _client()
    coord = _coordinator(client)
    number, select = _number(coord), _select(coord)
    await number.async_set_native_value(23.2)
    await select.async_select_option("window_heating")
    assert client.climate_targets.temp_c == 23.0  # snapped to the dial's grid
    assert client.climate_targets.window_heating_only is True
    assert select.current_option == "window_heating"
    coord._cariad_cmd.assert_not_called()
    coord.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_temperature_is_unavailable_in_window_heating_only():
    client = _client()
    coord = _coordinator(client)
    number, select = _number(coord), _select(coord)
    with patch.object(CoordinatorEntity, "available", new=True):
        assert number.available is True
        await select.async_select_option("window_heating")
        assert number.available is False
        coord.async_update_listeners.assert_called()  # the number re-renders
        await select.async_select_option("air_conditioning")
        assert number.available is True


def test_the_poll_never_overwrites_the_held_values():
    client = _client()
    client.store_climate_target_temperature(21.0)
    # What the app shows arrives with the poll; the entities keep HA's values.
    coord = _coordinator(client, {"target_temperature": 25.5,
                                  "climate_start_mode": "window_heating"})
    assert _number(coord).native_value == 21.0
    assert _select(coord).current_option == "air_conditioning"


@pytest.mark.asyncio
async def test_restore_after_a_restart():
    client = _client()
    coord = _coordinator(client)
    number, select = _number(coord), _select(coord)
    number.async_get_last_number_data = AsyncMock(
        return_value=SimpleNamespace(native_value=22.5)
    )
    select.async_get_last_state = AsyncMock(
        return_value=SimpleNamespace(state="window_heating")
    )
    with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
        await select.async_added_to_hass()
    assert client.climate_targets.temp_c == 22.5
    assert client.climate_targets.window_heating_only is True


@pytest.mark.asyncio
async def test_restore_falls_back_to_the_last_state_and_ignores_unknown():
    client = _client()
    coord = _coordinator(client)
    number, select = _number(coord), _select(coord)
    # An entity from before this change has no number extra data.
    number.async_get_last_number_data = AsyncMock(return_value=None)
    number.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="21.5"))
    select.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="unknown"))
    with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
        await select.async_added_to_hass()
    assert client.climate_targets.temp_c == 21.5
    assert client.climate_targets.window_heating_only is False

    number.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="unavailable"))
    fresh = _client()
    number.coordinator = _coordinator(fresh)
    with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert fresh.climate_targets.temp_c is None  # Start then leaves the dial alone


def test_not_companion_entries_get_no_targets():
    from custom_components.vag_connect.companion.client import climate_targets_of

    coord = MagicMock()
    coord.is_companion = MagicMock(return_value=False)
    assert climate_targets_of(coord) is None
    coord.is_companion = MagicMock(return_value=True)  # a MagicMock client
    assert climate_targets_of(coord) is None


@pytest.mark.asyncio
async def test_spawn_uses_the_held_number_and_adds_the_mode_select():
    from custom_components.vag_connect import number as number_mod
    from custom_components.vag_connect import select as select_mod

    client = _client()
    coord = _coordinator(client)
    coord.is_read_only = MagicMock(return_value=False)
    coord.command_capability_supported = MagicMock(return_value=None)
    coord.command_method_available = MagicMock(return_value=True)
    coord.read_capability_hidden = MagicMock(return_value=False)
    entry = MagicMock()
    entry.runtime_data = coord
    entry.data = {"brand": "volkswagen"}
    built: dict[str, list] = {}

    def capture(name):
        def spawner(_entry, _coord, _add, build):
            built[name] = build(VIN, {"has_battery": True})
        return spawner

    with patch.object(number_mod, "register_dynamic_spawner", capture("number")), \
            patch.object(number_mod, "_companion_can_sync", return_value=False), \
            patch.object(select_mod, "register_dynamic_spawner", capture("select")):
        await number_mod.async_setup_entry(MagicMock(), entry, MagicMock())
        await select_mod.async_setup_entry(MagicMock(), entry, MagicMock())
    temps = [e for e in built["number"] if e.entity_description.key == "target_temperature"]
    assert len(temps) == 1 and isinstance(temps[0], VagCompanionClimateTemperatureNumber)
    assert any(isinstance(e, VagCompanionClimateModeSelect) for e in built["select"])


def test_climate_entity_shows_the_held_temperature():
    from custom_components.vag_connect.climate import VagClimate

    client = _client()
    client.store_climate_target_temperature(24.0)
    coord = _coordinator(client, {"target_temperature": 20.0})
    coord.command_method_available = MagicMock(return_value=True)
    assert VagClimate(coord, VIN).target_temperature == 24.0


def test_with_nothing_held_the_number_shows_the_dial():
    # Live: number unknown while the sensor and the climate entity show 22.
    # Nothing held means Start leaves the dial, so the dial is what it applies.
    client = _client()
    coord = _coordinator(client, {"target_temperature": 22.0})
    number = _number(coord)
    assert number.native_value == 22.0
    # Shown, not held: a restart must not turn the dial reading into a target.
    assert number.extra_restore_state_data.native_value is None
    assert client.climate_targets.temp_c is None
    client.store_climate_target_temperature(23.0)
    assert number.extra_restore_state_data.native_value == 23.0


@pytest.mark.asyncio
async def test_restore_with_number_data_but_nothing_held_stores_nothing():
    client = _client()
    coord = _coordinator(client)
    number = _number(coord)
    number.async_get_last_number_data = AsyncMock(
        return_value=SimpleNamespace(native_value=None)
    )
    number.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="22.0"))
    with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
        await number.async_added_to_hass()
    assert client.climate_targets.temp_c is None


@pytest.mark.asyncio
async def test_set_temperature_with_hvac_mode_stores_then_starts():
    from custom_components.vag_connect.climate import VagClimate

    client = _client()
    coord = _coordinator(client)
    coord.command_method_available = MagicMock(return_value=True)
    seen: list[float | None] = []

    async def start(vin):
        seen.append(client.climate_targets.temp_c)

    coord.async_start_climatisation = start
    entity = VagClimate(coord, VIN)
    await entity.async_set_temperature(temperature=22.5, hvac_mode="heat_cool")
    assert seen == [22.5]  # stored first, so the Start applies it
    await entity.async_set_temperature(temperature=23.0)
    assert seen == [22.5]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["heat", "cool", "auto", "dry", "fan_only"])
async def test_set_temperature_with_an_unlisted_hvac_mode_sends_nothing(mode):
    # Through HA's own schema and service handler: "heat" passes HA's
    # validation, and must not become a Stop (only "off" means Stop).
    from homeassistant.components.climate import (
        SET_TEMPERATURE_SCHEMA,
        async_service_temperature_set,
    )
    from homeassistant.const import UnitOfTemperature
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.vag_connect.climate import VagClimate

    client = _client()
    coord = _coordinator(client, {"climatisation_active": True})
    coord.command_method_available = MagicMock(return_value=True)
    coord.async_start_climatisation = AsyncMock()
    coord.async_stop_climatisation = AsyncMock()
    entity = VagClimate(coord, VIN)
    entity.hass = MagicMock()
    entity.hass.config.units.temperature_unit = UnitOfTemperature.CELSIUS
    data = SET_TEMPERATURE_SCHEMA(
        {"entity_id": "climate.car", "temperature": 22, "hvac_mode": mode}
    )
    data.pop("entity_id")
    with pytest.raises(ServiceValidationError) as err:
        await async_service_temperature_set(entity, SimpleNamespace(data=data))
    assert err.value.translation_key == "hvac_mode_not_supported"
    assert err.value.translation_placeholders["hvac_mode"] == mode
    coord.async_start_climatisation.assert_not_called()
    coord.async_stop_climatisation.assert_not_called()
    assert client.climate_targets.temp_c is None  # nothing stored either
    with pytest.raises(ServiceValidationError):
        await entity.async_set_hvac_mode(mode)
    coord.async_stop_climatisation.assert_not_called()
    # The listed modes still work through the same handler.
    for ok, called in (("heat_cool", coord.async_start_climatisation),
                       ("off", coord.async_stop_climatisation)):
        data = SET_TEMPERATURE_SCHEMA(
            {"entity_id": "climate.car", "temperature": 22, "hvac_mode": ok}
        )
        data.pop("entity_id")
        await async_service_temperature_set(entity, SimpleNamespace(data=data))
        called.assert_awaited_once_with(VIN)
