# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion: entity names carry the ADB tag, cloud entries' names do not.

Live, the EU Data Act entry and the companion entry of one car each had a
device the user named "Tiguan", so both showed "Tiguan Battery Level".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.vag_connect.const import CONF_STRATEGY, STRATEGY_COMPANION_ADB
from custom_components.vag_connect.sensor import SENSOR_DESCRIPTIONS, VagConnectSensor

VIN = "WVGZZZCT8VW400704"
SOC = next(d for d in SENSOR_DESCRIPTIONS if d.key == "battery_soc")


def _sensor(companion: bool) -> VagConnectSensor:
    coord = MagicMock()
    coord.entry = SimpleNamespace(
        data={CONF_STRATEGY: STRATEGY_COMPANION_ADB} if companion else {"brand": "volkswagen"}
    )
    coord.data = {VIN: {}}
    sensor = VagConnectSensor(coord, VIN, SOC)
    key = f"component.vag_connect.entity.sensor.{SOC.translation_key}.name"
    sensor.platform = SimpleNamespace(
        platform_name="vag_connect", domain="sensor",
        platform_translations={key: "Battery Level"},
        object_id_platform_translations={key: "Battery Level"},
        component_translations={}, object_id_component_translations={},
    )
    return sensor


@pytest.mark.parametrize(("companion", "name"), [
    (True, "ADB Battery Level"), (False, "Battery Level"),
])
def test_the_name_and_the_derived_entity_id(companion, name):
    sensor = _sensor(companion)
    assert sensor.name == name
    assert sensor.suggested_object_id == name  # HA slugs it: tiguan_adb_battery_level
