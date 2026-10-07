# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""2026-10-07 — two VW app 4.6.4 pop-ups the companion clears on its own.

- The Google Maps consent on the Map tab (it blocks the parking read): agreed
  by tapping its "Agree" button, since BACK only leaves the map.
- The rating prompt (thumbs down / thumbs up, no close button): closed with
  BACK, so the app is never rated.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.vag_connect.companion.channel import CompanionChannel
from custom_components.vag_connect.companion.presets import PRESETS
from custom_components.vag_connect.companion.screen import find_overlay, parse_ui_dump


def _node(text: str = "", desc: str = "", rid: str = "", bounds: str = "[0,0][10,10]",
          clickable: bool = False) -> str:
    return (
        f'<node index="0" text="{text}" resource-id="{rid}" class="android.view.View" '
        f'package="com.volkswagen.weconnect" content-desc="{desc}" checkable="false" '
        f'checked="false" clickable="{str(clickable).lower()}" enabled="true" '
        f'focusable="false" focused="false" scrollable="false" long-clickable="false" '
        f'password="false" selected="false" bounds="{bounds}" />'
    )


def _dump(*nodes: str) -> str:
    return '<?xml version="1.0"?><hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"


# As seen live on 4.6.4 (2026-10-07), Map tab right after the update.
CONSENT = _dump(
    _node(rid="com.volkswagen.weconnect:id/google_maps_consent_fragment", bounds="[0,1028][1080,2064]"),
    _node(text="This app uses Google Maps", bounds="[53,1081][809,1158]"),
    _node(text="By using Google Maps, you give Volkswagen AG your consent to", bounds="[53,1200][1027,1728]"),
    _node(text="Agree", bounds="[485,1871][596,1922]"),
    _node(desc="Map Tab", rid="com.volkswagen.weconnect:id/cat_nav_map_tab_navigation",
          bounds="[360,2088][720,2193]", clickable=True),
)
CONSENT_NO_BUTTON = _dump(_node(text="This app uses Google Maps", bounds="[53,1081][809,1158]"))
# Layout dialog_app_rating_alert: title plus two icon-only buttons.
RATING = _dump(
    _node(text="How do you like the Volkswagen app? Give us your feedback.", rid="com.volkswagen.weconnect:id/title"),
    _node(rid="com.volkswagen.weconnect:id/cta_thumb_down", bounds="[60,900][520,1000]", clickable=True),
    _node(rid="com.volkswagen.weconnect:id/cta_thumb_up", bounds="[560,900][1020,1000]", clickable=True),
)
OVERVIEW = _dump(_node(desc="Climate control. On. Open details", clickable=True))


def _channel(*screens: str) -> tuple[CompanionChannel, MagicMock]:
    t = MagicMock()
    t.dump_ui = AsyncMock(side_effect=list(screens))
    t.tap = AsyncMock()
    t.key_back = AsyncMock()
    return CompanionChannel(t, PRESETS["volkswagen"], time_fn=lambda: 0.0), t


def test_both_pop_ups_are_recognised() -> None:
    vw = PRESETS["volkswagen"]
    assert find_overlay(parse_ui_dump(CONSENT), vw).name == "google_maps_consent"
    assert find_overlay(parse_ui_dump(RATING), vw).name == "app_rating"
    assert find_overlay(parse_ui_dump(OVERVIEW), vw) is None


@pytest.mark.asyncio
async def test_the_maps_consent_is_agreed_not_backed_out_of() -> None:
    ch, t = _channel(CONSENT, OVERVIEW)
    nodes, cleared = await ch._dump_and_clear_overlays()
    assert cleared is True
    t.tap.assert_awaited_once_with(540, 1896)  # centre of "Agree"
    t.key_back.assert_not_awaited()
    assert any("Climate control" in n.content_desc for n in nodes)


@pytest.mark.asyncio
async def test_without_its_button_the_consent_falls_back_to_back() -> None:
    ch, t = _channel(CONSENT_NO_BUTTON, OVERVIEW)
    _nodes, cleared = await ch._dump_and_clear_overlays()
    assert cleared is True
    t.key_back.assert_awaited_once()
    t.tap.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_rating_prompt_is_closed_with_back_never_rated() -> None:
    ch, t = _channel(RATING, OVERVIEW)
    _nodes, cleared = await ch._dump_and_clear_overlays()
    assert cleared is True
    t.key_back.assert_awaited_once()
    t.tap.assert_not_awaited()
