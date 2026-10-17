# SPDX-License-Identifier: AGPL-3.0-or-later
"""VW app 4.8.1 departure editor: hidden wheels set by SET_PROGRESS, days by button.

The fake phone is built from the live 4.8.1 captures (list, timer 3's page,
and the a11y helper's output of the same page) and behaves like the app: a day
button toggles its day, a second day forces Repeat on, Save shows only while
the page differs from the saved timer, X restores the saved timer, and Save
returns to the list with the new time and recurrence label.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from custom_components.vag_connect.companion import channel as channel_mod
from custom_components.vag_connect.companion import transport as transport_mod
from custom_components.vag_connect.companion.channel import CompanionChannel, CompanionWriteBlocked
from custom_components.vag_connect.companion.departure import (
    compose_day_chip,
    compose_repeat_switch,
    departure_rows,
    read_compose_clock,
    wheel_target,
)
from custom_components.vag_connect.companion.presets import PRESETS
from custom_components.vag_connect.companion.screen import parse_ui_dump
from custom_components.vag_connect.companion.transport import CompanionTransportError

FIXTURES = Path(__file__).parent / "fixtures" / "companion_departure"
LIST = (FIXTURES / "list_edit_481.xml").read_text(encoding="utf-8")
PAGE = (FIXTURES / "slot3_481.xml").read_text(encoding="utf-8")
TREE = (FIXTURES / "slot3_481_a11y.txt").read_text(encoding="utf-8")
STRINGS = {
    "departure_timer_subscreen_weekdays": {"Weekdays"},
    "weekday_saturday": {"Saturday"},
    "weekday_sunday": {"Sunday"},
    "weekday_monday": {"Monday"},
}
DAY_NAMES = {"sat": "Saturday", "sun": "Sunday", "mon": "Monday"}
SAVE = (
    '<node index="0" text="Save" resource-id="" class="android.widget.TextView" '
    'package="com.volkswagen.weconnect" content-desc="" checkable="false" checked="false" '
    'clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" '
    'long-clickable="false" password="false" selected="false" bounds="[916,82][1042,208]" />'
)


@dataclass(frozen=True)
class Timer:
    hour: int  # 1-12, AM only in these tests
    minute: int
    days: frozenset[str]
    repeat: bool


class EditorPhone:
    can_read_hidden_nodes = True
    connected = True

    def __init__(self, *, wheels_move: bool = True) -> None:
        self.saved = Timer(6, 0, frozenset({"sat"}), True)  # as captured
        self.edit = self.saved
        self.page = False
        self.wheels_move = wheels_move
        self.taps: list[str] = []
        self.helper: list[str] = []
        page = parse_ui_dump(PAGE)
        self.chips = {d: compose_day_chip(page, d).bounds for d in ("mon", "sat", "sun")}
        self.repeat_box = compose_repeat_switch(page).bounds
        self.row3 = departure_rows(parse_ui_dump(LIST))[2].clock.bounds

    async def connect(self) -> None:
        pass

    # -- screens --------------------------------------------------------------

    async def dump_ui(self) -> str:
        if not self.page:
            t = self.saved
            day = DAY_NAMES[next(iter(t.days))] if len(t.days) == 1 else "Weekdays"
            return LIST.replace('text="06:00"', f'text="{t.hour:02d}:{t.minute:02d}"').replace(
                'text="Saturday"', f'text="{day}"')
        xml = PAGE
        if not self.edit.repeat:
            xml = xml.replace('checked="true"', 'checked="false"')
        if self.edit != self.saved:
            xml = xml.replace("</hierarchy>", SAVE + "</hierarchy>")
        return xml

    async def a11y_prepare(self) -> None:
        self.helper.append("prepare")

    async def a11y_cleanup(self) -> None:
        self.helper.append("cleanup")

    async def a11y_tree(self) -> str:
        e = self.edit
        tree = re.sub(r"(desc=Hour\trange=)[\d.]+(/\S+\tstate=)\d+",
                      rf"\g<1>{60000 + e.hour % 12}.0\g<2>{e.hour:02d}", TREE)
        return re.sub(r"(desc=Minute\trange=)[\d.]+(/\S+\tstate=)\d+",
                      rf"\g<1>{60000 + e.minute // 5}.0\g<2>{e.minute:02d}", tree)

    async def a11y_set_progress(self, index: int, value: float) -> bool:
        self.helper.append(f"set {index} {value:g}")
        if not self.wheels_move:
            return True
        item = int(value) % 12
        if index == 0:
            self.edit = replace(self.edit, hour=item or 12)
        elif index == 1:
            self.edit = replace(self.edit, minute=item * 5)
        return True

    # -- input ----------------------------------------------------------------

    @staticmethod
    def _hit(box, x, y) -> bool:
        return box is not None and box[0] <= x < box[2] and box[1] <= y < box[3]

    async def tap(self, x: int, y: int) -> None:
        if not self.page:
            assert self._hit(self.row3, x, y), "only timer 3's row may be tapped on the list"
            self.page, self.edit = True, self.saved
            self.taps.append("open")
            return
        for day, box in self.chips.items():
            if self._hit(box, x, y):
                days = set(self.edit.days) ^ {day}
                assert days, "the app refuses a timer without a day"
                self.edit = replace(self.edit, days=frozenset(days),
                                    repeat=self.edit.repeat or len(days) > 1)
                self.taps.append(day)
                return
        if self._hit(self.repeat_box, x, y):
            self.edit = replace(self.edit, repeat=not self.edit.repeat)
            self.taps.append("repeat")
        elif self._hit((916, 82, 1042, 208), x, y):
            assert self.edit != self.saved, "Save tapped while not offered"
            self.saved, self.page = self.edit, False
            self.taps.append("save")
        elif self._hit((22, 82, 148, 208), x, y):
            self.edit = self.saved
            self.taps.append("x")
        else:
            raise AssertionError(f"unexpected tap at {x},{y}")

    async def key_back(self) -> None:
        self.page = False
        self.taps.append("back")


def _channel(phone: EditorPhone) -> CompanionChannel:
    ch = CompanionChannel(phone, PRESETS["volkswagen"], time_fn=lambda: 0.0)
    ch._app_strings = {k: set(v) for k, v in STRINGS.items()}
    return ch


@pytest.fixture(autouse=True)
def _no_wheel_wait(monkeypatch):
    monkeypatch.setattr(channel_mod, "_WHEEL_SETTLE_S", 0)


# -- the hidden picker --------------------------------------------------------


def test_live_capture_reads_the_hidden_wheels():
    clock = read_compose_clock(TREE)
    assert clock is not None
    assert (clock.time, clock.pm) == ("06:00", False)
    assert [w.index for w in (clock.hour, clock.minute, clock.meridiem)] == [0, 1, 2]
    assert (clock.hour.progress, clock.minute.progress) == (60005.0, 60000.0)


def test_wheels_are_found_by_structure_not_by_their_english_labels():
    german = TREE.replace("desc=Hour", "desc=Stunde").replace("desc=Minute", "desc=Minuten")
    assert read_compose_clock(german).time == "06:00"
    pm = TREE.replace("range=0.0/0.0/1.0\tstate=AM", "range=1.0/0.0/1.0\tstate=PM")
    assert read_compose_clock(pm).time == "18:00"


@pytest.mark.parametrize("mangle", [
    lambda t: t.replace("state=06", "state="),           # an unreadable hour
    lambda t: t.replace("range=0.0/0.0/1.0", "range=0.0/0.0/5.0"),  # no AM/PM wheel
    lambda t: t + "NODE\t1\t0\t0\t9\t9\tclass=x\tvis=true\tid=\ttext=\tdesc=\trange=1.0/0.0/9.0\tstate=3\n",
    lambda t: "",
])
def test_anything_unexpected_is_refused_rather_than_guessed(mangle):
    assert read_compose_clock(mangle(TREE)) is None


def test_wheels_take_the_short_way_round():
    clock = read_compose_clock(TREE)
    assert wheel_target(clock.hour, 6, 7, 12) == 60006.0
    assert wheel_target(clock.minute, 0, 11, 12) == 59999.0  # 00 -> 55 backwards


# -- the edit -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_sets_wheels_days_and_repeat_then_saves_once_and_reads_back():
    phone = EditorPhone()
    ch = _channel(phone)
    listing = parse_ui_dump(await phone.dump_ui())
    back = await ch._edit_timer(listing, 3, (7, 5), ("sun",), False)
    assert phone.saved == Timer(7, 5, frozenset({"sun"}), False)
    # Sunday added before Saturday is removed; the app's forced Repeat undone.
    assert phone.taps.count("save") == 1
    assert phone.taps.index("sun") < phone.taps.index("sat") < phone.taps.index("repeat")
    assert phone.taps.index("repeat") < phone.taps.index("save")
    assert phone.helper[0] == "prepare" and "cleanup" in phone.helper
    assert departure_rows(back)
    assert ch._nav_cache["departure_timer_3_time"] == "07:05"
    assert ch._nav_cache["departure_timer_3_weekdays"] == "sun"
    assert ch._nav_cache["departure_timer_3_repeat"] is False


@pytest.mark.asyncio
async def test_nothing_to_change_sends_nothing():
    phone = EditorPhone()
    ch = _channel(phone)
    await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (6, 0), ("sat",), True)
    assert "save" not in phone.taps
    assert not [h for h in phone.helper if h.startswith("set")]


@pytest.mark.asyncio
async def test_a_wheel_that_does_not_move_cancels_with_x_and_saves_nothing():
    phone = EditorPhone(wheels_move=False)
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked, match="nothing was saved"):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), ("sat",), True)
    assert "save" not in phone.taps
    assert phone.saved == Timer(6, 0, frozenset({"sat"}), True)


@pytest.mark.asyncio
async def test_a_day_change_that_did_not_reach_the_wheels_is_cancelled():
    phone = EditorPhone(wheels_move=False)
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), ("mon",), True)
    assert "x" in phone.taps and "save" not in phone.taps
    assert phone.saved.days == frozenset({"sat"})


@pytest.mark.asyncio
async def test_one_time_timer_needs_exactly_one_day():
    phone = EditorPhone()
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked, match="exactly one weekday"):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, None, ("sat", "sun"), False)
    assert "save" not in phone.taps


@pytest.mark.asyncio
async def test_a_connection_without_the_helper_refuses_before_any_editor_tap():
    phone = EditorPhone()
    phone.can_read_hidden_nodes = False  # e.g. the agent relay
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked, match="direct ADB connection"):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), None, None)
    assert phone.taps == ["open", "back"]


# -- the shipped helper -------------------------------------------------------


def test_the_shipped_helper_is_the_reviewed_build():
    dex = Path(transport_mod.__file__).parent / "a11y" / "a11y_tree.dex"
    assert hashlib.sha256(dex.read_bytes()).hexdigest() == transport_mod.A11Y_DEX_SHA256
    assert (dex.parent / "A11yTree.java").is_file()


def test_a_modified_helper_is_never_pushed(monkeypatch):
    monkeypatch.setattr(transport_mod, "A11Y_DEX_SHA256", "0" * 64)
    with pytest.raises(CompanionTransportError, match="reviewed build"):
        transport_mod._a11y_dex_path()


def test_only_the_direct_adb_transport_offers_the_helper():
    from custom_components.vag_connect.companion.addon_transport import AddOnAdbTransport
    from custom_components.vag_connect.companion.relay_transport import AgentRelayTransport

    assert transport_mod.NetworkAdbTransport.can_read_hidden_nodes is True
    assert AddOnAdbTransport.can_read_hidden_nodes is False
    assert AgentRelayTransport.can_read_hidden_nodes is False
