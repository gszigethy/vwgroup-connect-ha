# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map navigation across app generations; no marker or Share taps."""
from dataclasses import replace

import pytest

from custom_components.vag_connect.companion.channel import CompanionChannel
from custom_components.vag_connect.companion.presets import PRESETS
from custom_components.vag_connect.companion.resources import VEHICLE_LOCATION
from custom_components.vag_connect.companion.screen import UiNode

VW = PRESETS['volkswagen']
STEP = next(n for n in VW.nav_reads if n.name == 'parking_position').path[1]
BUTTON = UiNode('', 'Vehicle location', '', 'android.widget.Button', True, (800, 900, 950, 1050))


@pytest.mark.parametrize('label', ['Vehicle location', 'Find vehicle', 'Fahrzeug finden'])
def test_new_and_legacy_labels_without_tables(label):
    node = replace(BUTTON, content_desc=label)
    channel = CompanionChannel(object(), VW, time_fn=lambda: 0)
    assert channel._step_node([node], STEP) is node


def test_installed_translation_takes_precedence_over_fallback():
    translated = replace(BUTTON, content_desc='Fahrzeugstandort')
    channel = CompanionChannel(object(), VW, time_fn=lambda: 0)
    channel._app_strings = {VEHICLE_LOCATION: {'Fahrzeugstandort'}}
    assert channel._step_node([BUTTON, translated], STEP) is translated


@pytest.mark.parametrize('change', [{'enabled': False}, {'bounds': (0, 0, 0, 0)},
                                  {'content_desc': 'My location'}])
def test_unavailable_or_unrelated_controls_do_not_match(change):
    channel = CompanionChannel(object(), VW, time_fn=lambda: 0)
    assert channel._step_node([replace(BUTTON, **change)], STEP) is None
