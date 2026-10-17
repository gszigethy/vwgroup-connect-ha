# SPDX-License-Identifier: AGPL-3.0-or-later
"""VW app 4.8.1 departure editor: hidden wheels set by SET_PROGRESS, days by button.

The fake phone is built from the live 4.8.1 captures (list, timer 3's page,
and the a11y helper's output of the same page) and behaves like the app: Save
shows only while the page differs from the saved timer, X restores the saved
timer, and Save returns to the list with the new time. The page never shows
which weekdays are on, so a change of days is refused before any tap.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from custom_components.vag_connect.companion import channel as channel_mod
from custom_components.vag_connect.companion import transport as transport_mod
from custom_components.vag_connect.companion.channel import CompanionChannel, CompanionWriteBlocked
from custom_components.vag_connect.companion.departure import (
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
    hour: int  # 0-23
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
        self.fail_set: BaseException | None = None
        self.connects = 0
        self.taps: list[str] = []
        self.helper: list[str] = []
        page = parse_ui_dump(PAGE)
        self.chips = {
            n.resource_id.removeprefix("cta_").lower()[:3]: n.bounds
            for n in page if n.resource_id.startswith("cta_")
        }
        self.repeat_box = compose_repeat_switch(page).bounds
        self.row3 = departure_rows(parse_ui_dump(LIST))[2].clock.bounds

    async def connect(self) -> None:
        self.connects += 1
        self.connected = True

    # -- screens --------------------------------------------------------------

    async def dump_ui(self) -> str:
        if not self.page:
            t = self.saved
            day = DAY_NAMES[next(iter(t.days))] if len(t.days) == 1 else "Weekdays"
            clock = f'text="{(t.hour % 12 or 12):02d}:{t.minute:02d}"'
            head, _, tail = LIST.partition('text="06:00"')
            tail = tail.replace('text="AM"', f'text="{"PM" if t.hour >= 12 else "AM"}"', 1)
            return (head + clock + tail).replace('text="Saturday"', f'text="{day}"')
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
        h12 = e.hour % 12 or 12
        tree = re.sub(r"(desc=Hour\trange=)[\d.]+(/\S+\tstate=)\d+",
                      rf"\g<1>{60000 + h12 - 1}.0\g<2>{h12:02d}", TREE)
        tree = re.sub(r"(desc=AM PM\trange=)[\d.]+(/\S+\tstate=)\w+",
                      rf"\g<1>{1 if e.hour >= 12 else 0}.0\g<2>{'PM' if e.hour >= 12 else 'AM'}", tree)
        return re.sub(r"(desc=Minute\trange=)[\d.]+(/\S+\tstate=)\d+",
                      rf"\g<1>{60000 + e.minute // 5}.0\g<2>{e.minute:02d}", tree)

    async def a11y_set_progress(self, index: int, value: float) -> bool:
        self.helper.append(f"set {index} {value:g}")
        if self.fail_set is not None:
            raise self.fail_set
        if not self.wheels_move:
            return True
        e = self.edit
        if index == 0:  # the hour list is 1..12, so progress 60000 shows 01
            h12 = int(value) % 12 + 1
            self.edit = replace(e, hour=h12 % 12 + (12 if e.hour >= 12 else 0))
        elif index == 1:
            self.edit = replace(e, minute=int(value) % 12 * 5)
        elif index == 2:
            self.edit = replace(e, hour=e.hour % 12 + (12 if round(value) == 1 else 0))
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
async def test_edit_sets_wheels_and_repeat_then_saves_once_and_reads_back():
    phone = EditorPhone()
    ch = _channel(phone)
    listing = parse_ui_dump(await phone.dump_ui())
    back = await ch._edit_timer(listing, 3, (7, 5), ("sat",), False)
    assert phone.saved == Timer(7, 5, frozenset({"sat"}), False)
    # No day button is ever tapped; the page is reopened after Save to read Repeat.
    assert phone.taps == ["open", "repeat", "save", "open", "back"]
    assert phone.helper[0] == "prepare" and phone.helper[-1] == "cleanup"
    assert departure_rows(back)
    assert ch._nav_cache["departure_timer_3_time"] == "07:05"
    assert ch._nav_cache["departure_timer_3_weekdays"] == "sat"
    assert ch._nav_cache["departure_timer_3_repeat"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [("sun",), ("sat", "sun"), ("mon", "tue", "wed", "thu", "fri")])
async def test_a_change_of_days_is_refused_before_any_tap(days):
    phone = EditorPhone()
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked, match="change the days in the app"):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), days, True)
    assert phone.taps == ["open"]  # only the row was opened
    assert not [h for h in phone.helper if h.startswith("set")]
    assert phone.helper[-1] == "cleanup"


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
async def test_a_repeat_change_whose_wheels_do_not_move_is_cancelled_with_x():
    phone = EditorPhone(wheels_move=False)
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), None, False)
    assert phone.taps[-1] == "x" and "save" not in phone.taps
    assert phone.saved == Timer(6, 0, frozenset({"sat"}), True)


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



@pytest.mark.asyncio
async def test_pm_times_set_the_meridiem_wheel_and_read_back():
    phone = EditorPhone()
    ch = _channel(phone)
    await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (18, 30), None, None)
    assert phone.saved == Timer(18, 30, frozenset({"sat"}), True)
    assert any(h.startswith("set 2 ") for h in phone.helper)  # the AM/PM wheel moved


@pytest.mark.asyncio
async def test_task_cancellation_mid_edit_still_presses_x():
    phone = EditorPhone()
    phone.fail_set = asyncio.CancelledError()
    ch = _channel(phone)
    with pytest.raises(asyncio.CancelledError):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), None, False)
    assert "x" in phone.taps and "save" not in phone.taps
    assert phone.saved == Timer(6, 0, frozenset({"sat"}), True)
    assert phone.helper[-1] == "cleanup"


@pytest.mark.asyncio
async def test_a_dropped_link_reconnects_to_cancel_and_remove_the_helper():
    phone = EditorPhone()

    class Dropped(CompanionTransportError):
        pass

    phone.fail_set = Dropped("link dropped")
    original = phone.a11y_set_progress

    async def drop(index, value):
        phone.connected = False
        return await original(index, value)

    phone.a11y_set_progress = drop
    ch = _channel(phone)
    with pytest.raises(CompanionWriteBlocked, match="link dropped"):
        await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 0), None, False)
    assert phone.connects >= 1
    assert "x" in phone.taps and "save" not in phone.taps
    assert phone.helper[-1] == "cleanup"


@pytest.mark.asyncio
async def test_saving_refreshes_the_enabled_count():
    phone = EditorPhone()
    ch = _channel(phone)
    ch._nav_cache["departure_timer_enabled_count"] = 7  # stale on purpose
    await ch._edit_timer(parse_ui_dump(await phone.dump_ui()), 3, (7, 5), None, None)
    assert ch._nav_cache.get("departure_timer_enabled_count") != 7
