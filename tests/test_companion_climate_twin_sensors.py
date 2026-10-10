# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion: a read-only sensor is not created next to the switch showing it.

The Air Conditioning Settings switches and the window heating switch show the
same field the diagnostic binary sensors read, so where the switch exists the
sensor only repeats it. An entry created by an earlier version is removed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.vag_connect import binary_sensor as bs
from custom_components.vag_connect.const import vehicle_unique_id

VIN = "WVGZZZCT8VW400704"
TWINS = (
    "climate_at_unlock", "window_heating_enabled",
    "climate_zone_front_left", "climate_zone_front_right", "window_heating_front",
)


class _Client:
    command_set_climate_at_unlock = command_set_window_heating_auto = None
    command_set_climate_zone_front_left = command_set_climate_zone_front_right = None
    command_start_window_heating = None


def _coordinator(*, companion=True, read_only=False, writes=True):
    coord = MagicMock()
    coord.is_companion = MagicMock(return_value=companion)
    coord.is_read_only = MagicMock(return_value=read_only)
    coord.command_capability_supported = MagicMock(return_value=None)
    coord.command_method_available = MagicMock(return_value=writes)
    coord._cariad_client = _Client()
    coord.vehicles = coord.data = {VIN: {
        "vin": VIN, "climate_at_unlock": False, "window_heating_enabled": True,
        "climate_zone_front_left": True, "climate_zone_front_right": False,
        "window_heating_front": False, "window_heating_back": False,
    }}
    return coord


def _keys(coord, registry=None):
    entry = MagicMock()
    entry.runtime_data = coord
    entry.data = {}
    entry.options = {}
    added: list = []
    registry = registry or MagicMock(async_get_entity_id=MagicMock(return_value=None))
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=registry):
        asyncio.run(bs.async_setup_entry(MagicMock(), entry, lambda e, **_k: added.extend(e)))
    return {getattr(getattr(e, "entity_description", None), "key", None) for e in added}


def test_the_twins_are_not_created_where_the_switch_exists():
    keys = _keys(_coordinator())
    assert not keys & set(TWINS)
    assert "window_heating_back" in keys  # no switch for it: still a sensor


@pytest.mark.parametrize("coord_kw", [
    {"companion": False}, {"read_only": True}, {"writes": False},
])
def test_without_the_switch_the_sensor_stays(coord_kw):
    assert set(TWINS) <= _keys(_coordinator(**coord_kw))


def test_an_entry_from_an_earlier_version_is_removed():
    registry = MagicMock()
    registry.async_get_entity_id = MagicMock(
        side_effect=lambda domain, platform, uid: (
            "binary_sensor.tiguan_adb_climate_at_unlock"
            if uid == vehicle_unique_id(VIN, "climate_at_unlock", companion=True) else None
        )
    )
    _keys(_coordinator(), registry)
    registry.async_remove.assert_called_once_with("binary_sensor.tiguan_adb_climate_at_unlock")
