# Companion climate rationalisation — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On Companion (ADB) entries, run climate from one climate entity (on/off, temperature, presets *Air conditioning* / *Window heating*), retire the five entities it replaces, and put the zone switches in Controls.

**Architecture:** A `VagCompanionClimate` subclass of the shared `VagClimate`, created only on Companion entries with the same unique id. It drives the client's existing held targets (`ClimateTargets.window_heating_only`, `temp_c`) that the select and number drive today, and takes over their restore logic. Retired entities are skipped on Companion entries and their registry entries removed with the existing `remove_twin` helper.

**Tech Stack:** Home Assistant custom integration (Python 3.13, `homeassistant` climate/restore APIs), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-13-companion-climate-rationalisation-design.md`

## Global Constraints

- Companion (ADB) entries only. Cloud entries keep `VagClimate`, `VagClimatisationSwitch`, `VagWindowHeatingSwitch`, their number and select unchanged.
- Never wire Companion values into EU Data Act fields; stay inside the Companion code paths.
- Unique id and entity id of the climate entity unchanged (`vehicle_unique_id(vin, "climate", companion=True)`).
- Presets: `air_conditioning` (default), `window_heating`. HVAC modes `off`, `heat_cool`. No `hvac_action`, fan or swing modes.
- A preset change while off sends nothing to the phone or car; while running it is refused.
- After a window-heating run ends, the preset returns to `air_conditioning` (mirrors the app).
- Every command keeps the existing guards (request-limit pause, Read-only Mode, 60 s gap); Read-only Mode creates no climate entity.
- Breaking change: highlighted in the CHANGELOG with a **⚠️ Breaking** block.
- Base branch: `companion/climate-rationalisation`, rebased onto `releases` after PR #102 (which adds `_COMPANION_CLIMATE_CONTROL_KEYS` in `switch.py`) is merged.
- Test venv: `source ~/dev/venv-ha-latest/bin/activate`. CI mypy flags: `--ignore-missing-imports --disallow-untyped-defs --disallow-incomplete-defs --warn-return-any`.
- Commits: no co-author or AI trailers.

## Review Focus

1. Window heating running alone must show the climate entity as **on** (today `hvac_mode` follows only `climatisation_active`). Test in Task 1.
2. Choosing *Window heating* and then never starting must keep the choice across reads (the fallback only fires after a run was seen). Test in Task 3.
3. A restart while *Window heating* is chosen must restore it, and a restart must never restore a temperature that was only shown, not held. Tests in Task 2.
4. A preset change during the request-limit pause must succeed (local), while `turn_on` is still refused. Test in Task 1.
5. Cloud entries must still get the shared switches, select and number. Test in Task 4.

---

### Task 1: `VagCompanionClimate` with presets

**Files:**
- Modify: `custom_components/vag_connect/climate.py`
- Modify: `custom_components/vag_connect/strings.json`, `custom_components/vag_connect/translations/*.json` (12 files)
- Test: `tests/test_companion_climate_entity.py` (new)

**Interfaces:**
- Consumes: `climate_targets_of(coordinator) -> ClimateTargets | None`, `CompanionClient.store_climate_start_mode(window_heating_only: bool) -> None` (both `companion/client.py`); `coordinator.async_start_climatisation(vin)`, `async_stop_climatisation(vin)`.
- Produces: `class VagCompanionClimate(VagClimate)` with `PRESET_AIR_CONDITIONING = "air_conditioning"`, `PRESET_WINDOW_HEATING = "window_heating"` (module constants in `climate.py`), `preset_mode`, `async_set_preset_mode`, `_running() -> bool`. Exception translation key `climate_preset_while_running`.

- [ ] **Step 1: Write the failing tests** in `tests/test_companion_climate_entity.py`

```python
# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Companion climate entity: one place for on/off, temperature and the mode."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.exceptions import ServiceValidationError

from custom_components.vag_connect.climate import (
    PRESET_AIR_CONDITIONING,
    PRESET_WINDOW_HEATING,
    VagClimate,
    VagCompanionClimate,
)
from custom_components.vag_connect.companion.client import CompanionClient

VIN = "WVWZZZTESTVIN0001"


class _TrippedChannel:
    def __getattr__(self, name):  # pragma: no cover - must not run
        raise AssertionError(f"the channel was touched: {name}")


def _client() -> CompanionClient:
    client = CompanionClient.__new__(CompanionClient)
    client._brand = "volkswagen"
    client._channel = _TrippedChannel()
    return client


def _coord(client: CompanionClient, vehicle: dict | None = None):
    coord = MagicMock()
    coord.is_companion = MagicMock(return_value=True)
    coord.command_method_available = MagicMock(return_value=True)
    coord._cariad_client = client
    coord.data = {VIN: dict(vehicle or {})}
    coord.last_update_success = True
    coord.async_start_climatisation = AsyncMock()
    coord.async_stop_climatisation = AsyncMock()
    return coord


def _entity(coord) -> VagCompanionClimate:
    e = VagCompanionClimate(coord, VIN)
    e.async_write_ha_state = MagicMock()
    return e


def test_same_unique_id_as_the_shared_entity():
    coord = _coord(_client())
    assert VagCompanionClimate(coord, VIN).unique_id == VagClimate(coord, VIN).unique_id


def test_presets_and_default():
    e = _entity(_coord(_client()))
    assert e.preset_modes == [PRESET_AIR_CONDITIONING, PRESET_WINDOW_HEATING]
    assert e.preset_mode == PRESET_AIR_CONDITIONING


@pytest.mark.asyncio
async def test_preset_while_off_only_stores():
    client = _client()
    coord = _coord(client)
    e = _entity(coord)
    await e.async_set_preset_mode(PRESET_WINDOW_HEATING)
    assert client.climate_targets.window_heating_only is True
    assert e.preset_mode == PRESET_WINDOW_HEATING
    coord.async_start_climatisation.assert_not_called()


@pytest.mark.asyncio
async def test_preset_while_off_is_allowed_during_the_pause():
    # Local only: no command path, so no request-limit check is reached.
    client = _client()
    coord = _coord(client)
    coord.async_start_climatisation = AsyncMock(side_effect=AssertionError("no start"))
    await _entity(coord).async_set_preset_mode(PRESET_WINDOW_HEATING)
    assert client.climate_targets.window_heating_only is True


@pytest.mark.asyncio
@pytest.mark.parametrize("vehicle", [
    {"climatisation_active": True},
    {"climatisation_active": False, "window_heating_front": True},
])
async def test_preset_change_while_running_is_refused(vehicle):
    client = _client()
    e = _entity(_coord(client, vehicle))
    with pytest.raises(ServiceValidationError):
        await e.async_set_preset_mode(PRESET_WINDOW_HEATING)
    assert client.climate_targets.window_heating_only is False


@pytest.mark.asyncio
async def test_unknown_preset_is_refused():
    e = _entity(_coord(_client()))
    with pytest.raises(ServiceValidationError):
        await e.async_set_preset_mode("boost")


def test_window_heating_alone_shows_on():
    e = _entity(_coord(_client(), {"climatisation_active": False, "window_heating_front": True}))
    assert e.hvac_mode == HVACMode.HEAT_COOL
    assert e.preset_mode == PRESET_WINDOW_HEATING


def test_running_preset_follows_the_app():
    e = _entity(_coord(_client(), {"climatisation_active": True, "climate_start_mode": "air_conditioning"}))
    assert e.preset_mode == PRESET_AIR_CONDITIONING


@pytest.mark.asyncio
async def test_turn_on_starts_and_turn_off_stops():
    coord = _coord(_client())
    e = _entity(coord)
    await e.async_turn_on()
    coord.async_start_climatisation.assert_awaited_once_with(VIN)
    await e.async_turn_off()
    coord.async_stop_climatisation.assert_awaited_once_with(VIN)


@pytest.mark.asyncio
async def test_turn_on_with_window_heating_chosen_uses_the_held_mode():
    # The client's command_start_climate starts what ClimateTargets holds.
    client = _client()
    coord = _coord(client)
    e = _entity(coord)
    await e.async_set_preset_mode(PRESET_WINDOW_HEATING)
    await e.async_turn_on()
    coord.async_start_climatisation.assert_awaited_once_with(VIN)
    assert client.climate_targets.window_heating_only is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `source ~/dev/venv-ha-latest/bin/activate && python -m pytest -q tests/test_companion_climate_entity.py`
Expected: FAIL, `ImportError: cannot import name 'PRESET_AIR_CONDITIONING'`.

- [ ] **Step 3: Implement** in `climate.py`

Imports to add: `from homeassistant.exceptions import ServiceValidationError` (already imported — keep one), `from .const import DOMAIN` (already imported).

In `async_setup_entry._build_for_vin`, replace `return [VagClimate(coordinator, vin)]` with:

```python
        if coordinator.is_companion():
            return [VagCompanionClimate(coordinator, vin)]
        return [VagClimate(coordinator, vin)]
```

Append after `VagClimate`:

```python
PRESET_AIR_CONDITIONING = "air_conditioning"
PRESET_WINDOW_HEATING = "window_heating"


class VagCompanionClimate(VagClimate):
    """Companion: the one place to run climate.

    The app's *Select mode* picker only chooses what Start starts, and one
    Stop ends either mode. So the mode is a preset: chosen while off it is
    held in HA for the next start (nothing is sent), while running it shows
    what runs and cannot be changed. Same unique id as the shared entity.
    """

    _attr_preset_modes = [PRESET_AIR_CONDITIONING, PRESET_WINDOW_HEATING]

    def __init__(self, coordinator: VagConnectCoordinator, vin: str) -> None:
        super().__init__(coordinator, vin)
        self._attr_supported_features |= (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    def _targets(self) -> ClimateTargets | None:
        from .companion.client import climate_targets_of  # noqa: PLC0415

        return climate_targets_of(self.coordinator)

    def _running(self) -> bool:
        v = self._vehicle
        return bool(v.get("climatisation_active")) or bool(v.get("window_heating_front"))

    @property
    def hvac_mode(self) -> HVACMode:
        # Window heating alone is climate running too: the app's Stop ends it.
        return HVACMode.HEAT_COOL if self._running() else HVACMode.OFF

    @property
    def preset_mode(self) -> str:
        if self._running():
            if self._vehicle.get("climatisation_active"):
                shown = self._vehicle.get("climate_start_mode")
                return PRESET_WINDOW_HEATING if shown == PRESET_WINDOW_HEATING else PRESET_AIR_CONDITIONING
            return PRESET_WINDOW_HEATING
        targets = self._targets()
        if targets is not None and targets.window_heating_only:
            return PRESET_WINDOW_HEATING
        return PRESET_AIR_CONDITIONING

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self.preset_modes:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="climate_preset_not_supported",
                translation_placeholders={
                    "preset": str(preset_mode), "presets": ", ".join(self.preset_modes),
                },
            )
        if self._running():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="climate_preset_while_running",
            )
        store = getattr(self.coordinator._cariad_client, "store_climate_start_mode", None)
        if callable(store):
            store(preset_mode == PRESET_WINDOW_HEATING)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
```

Add `from .companion.client import ClimateTargets` under `if TYPE_CHECKING:` at the top of `climate.py` (create the block if absent, with `from typing import TYPE_CHECKING`).

- [ ] **Step 4: Translations.** In `strings.json` and every `translations/*.json`:
  - under `entity.climate.climate` add
    ```json
    "state_attributes": {"preset_mode": {"state": {
      "air_conditioning": "<AC>", "window_heating": "<WH>"}}}
    ```
  - under `exceptions` add `climate_preset_while_running` ("Stop the climate first: the mode cannot change while it runs. Nothing was sent.") and `climate_preset_not_supported` ("The mode {preset} is not supported; use one of: {presets}. Nothing was sent.").
  - Names per language — en: Air conditioning / Window heating; de: Klimatisierung / Scheibenheizung; take the other 10 from the existing `select.companion_climate_start_mode.state` values in each file (same words), and translate the two messages in each language.

- [ ] **Step 5: Run tests**

Run: `python -m pytest -q tests/test_companion_climate_entity.py tests/test_478_porsche_reference_parity.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/vag_connect/climate.py custom_components/vag_connect/strings.json custom_components/vag_connect/translations tests/test_companion_climate_entity.py
git commit -m "Companion climate: presets for air conditioning and window heating"
```

### Task 2: The climate entity restores the held mode and temperature

**Files:**
- Modify: `custom_components/vag_connect/climate.py`
- Test: `tests/test_companion_climate_entity.py`

**Interfaces:**
- Consumes: `CompanionClient.restore_climate_target_temperature(temp_c: float, app_dial_c: float | None)`, `store_climate_start_mode`, `ClimateTargets.temp_c / app_dial_c / window_heating_only`.
- Produces: `VagCompanionClimate` is a `RestoreEntity`; its state attributes carry nothing new — the held values go in `extra_restore_state_data` as `{"held_temp_c", "app_dial_c", "window_heating_only"}`.

- [ ] **Step 1: Failing tests** (append)

```python
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import CoordinatorEntity


def _read(client, value):
    client.climate_targets.note_app_dial(value)


def test_saved_data_holds_only_held_values():
    client = _client()
    _read(client, 20.0)
    e = _entity(_coord(client, {"target_temperature": 20.0}))
    assert e.extra_restore_state_data.as_dict() == {
        "held_temp_c": None, "app_dial_c": 20.0, "window_heating_only": False,
    }
    client.store_climate_target_temperature(23.0)
    client.store_climate_start_mode(True)
    assert e.extra_restore_state_data.as_dict() == {
        "held_temp_c": 23.0, "app_dial_c": 20.0, "window_heating_only": True,
    }


async def _restore(client, saved):
    e = _entity(_coord(client))
    e.async_get_last_extra_data = AsyncMock(
        return_value=SimpleNamespace(as_dict=lambda: saved) if saved is not None else None
    )
    with patch.object(CoordinatorEntity, "async_added_to_hass", new=AsyncMock()):
        await e.async_added_to_hass()
    return e


@pytest.mark.asyncio
async def test_restart_restores_mode_and_temperature():
    client = _client()
    await _restore(client, {"held_temp_c": 23.0, "app_dial_c": 20.0, "window_heating_only": True})
    assert client.climate_targets.window_heating_only is True
    assert client.climate_targets.temp_c == 23.0
    _read(client, 19.0)  # dial moved in the app while HA was down: it wins
    assert client.climate_targets.temp_c == 19.0


@pytest.mark.asyncio
async def test_restart_with_nothing_saved_holds_nothing():
    client = _client()
    await _restore(client, None)
    assert client.climate_targets.temp_c is None
    assert client.climate_targets.window_heating_only is False
```

- [ ] **Step 2: Run** `python -m pytest -q tests/test_companion_climate_entity.py` — Expected: FAIL (`extra_restore_state_data` missing / not a RestoreEntity).

- [ ] **Step 3: Implement.** Change the class line to `class VagCompanionClimate(VagClimate, RestoreEntity):` (import `from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity`) and add:

```python
@dataclass
class _HeldClimate(ExtraStoredData):
    """What HA holds for the next Start, with the dial it was held against."""

    held_temp_c: float | None
    app_dial_c: float | None
    window_heating_only: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "held_temp_c": self.held_temp_c,
            "app_dial_c": self.app_dial_c,
            "window_heating_only": self.window_heating_only,
        }
```

(module level, above `VagCompanionClimate`; `from dataclasses import dataclass`, `from typing import Any`.) Inside the class:

```python
    @property
    def extra_restore_state_data(self) -> _HeldClimate:
        # Only held values: a dial reading shown in their place must never come
        # back as a target, or the next Start would move the dial.
        t = self._targets()
        return _HeldClimate(
            t.temp_c if t is not None else None,
            t.app_dial_c if t is not None else None,
            bool(t.window_heating_only) if t is not None else False,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        extra = await self.async_get_last_extra_data()
        if extra is None:
            return
        saved = extra.as_dict()
        client = self.coordinator._cariad_client
        if saved.get("window_heating_only") is True:
            client.store_climate_start_mode(True)
        held = saved.get("held_temp_c")
        dial = saved.get("app_dial_c")
        if isinstance(held, (int, float)) and not isinstance(held, bool):
            client.restore_climate_target_temperature(
                float(held), float(dial) if isinstance(dial, (int, float)) else None,
            )
```

- [ ] **Step 4: Run** the file again — Expected: PASS.

- [ ] **Step 5: Commit** `git commit -am "Companion climate: restore the held mode and temperature"`

### Task 3: The preset returns to air conditioning after a window-heating run

**Files:**
- Modify: `custom_components/vag_connect/climate.py`
- Test: `tests/test_companion_climate_entity.py`

**Interfaces:**
- Consumes: Task 1 `_running()`, Task 2 restore.
- Produces: `VagCompanionClimate._handle_coordinator_update()` override; attribute `_window_heating_seen: bool`.

- [ ] **Step 1: Failing tests** (append)

```python
def _poll(e, coord, vehicle):
    coord.data[VIN] = dict(vehicle)
    e._handle_coordinator_update()


def test_window_heating_run_ends_back_to_air_conditioning():
    client = _client()
    client.store_climate_start_mode(True)
    coord = _coord(client)
    e = _entity(coord)
    _poll(e, coord, {"window_heating_front": True})
    assert e.preset_mode == PRESET_WINDOW_HEATING
    _poll(e, coord, {"window_heating_front": False})
    assert client.climate_targets.window_heating_only is False
    assert e.preset_mode == PRESET_AIR_CONDITIONING


def test_a_choice_never_started_is_kept():
    client = _client()
    client.store_climate_start_mode(True)
    coord = _coord(client)
    e = _entity(coord)
    for _ in range(3):
        _poll(e, coord, {"window_heating_front": False, "climatisation_active": False})
    assert client.climate_targets.window_heating_only is True
```

- [ ] **Step 2: Run** — Expected: first test FAILS (preset stays window heating).

- [ ] **Step 3: Implement** in `VagCompanionClimate`:

```python
    _window_heating_seen = False

    def _handle_coordinator_update(self) -> None:
        # Mirror the app: a window-heating Start is one-shot. Once a run was
        # seen and has ended (Stop, the car's timer, or the app), the next
        # Start is air conditioning again. A choice never started is kept.
        t = self._targets()
        if t is not None and t.window_heating_only:
            if self._running():
                self._window_heating_seen = True
            elif self._window_heating_seen:
                self._window_heating_seen = False
                self.coordinator._cariad_client.store_climate_start_mode(False)
        super()._handle_coordinator_update()
```

- [ ] **Step 4: Run** — Expected: PASS.

- [ ] **Step 5: Commit** `git commit -am "Companion climate: window heating is one-shot, as in the app"`

### Task 4: Retire the replaced entities; zone switches to Controls

**Files:**
- Modify: `custom_components/vag_connect/switch.py`, `select.py`, `number.py`, `sensor.py`, `companion/entity_twins.py`
- Modify: `tests/test_companion_climate_start_targets.py` (drop tests of the removed number/select classes' Companion creation; keep the `ClimateTargets` tests), any test asserting those entities on Companion entries (find with `grep -rln "VagCompanionClimateModeSelect\|VagCompanionClimateTemperatureNumber\|VagWindowHeatingSwitch\|VagClimatisationSwitch" tests`)
- Test: `tests/test_companion_climate_retired.py` (new)

**Interfaces:**
- Consumes: `remove_twin(hass, platform, vin, key)` (`companion/entity_twins.py`), `_COMPANION_CLIMATE_CONTROL_KEYS` (`switch.py`, from PR #102).
- Produces: `RETIRED_COMPANION_CLIMATE: frozenset[tuple[str, str]]` in `companion/entity_twins.py` =
  `{("switch", "climatisation_switch"), ("switch", "window_heating_switch"), ("select", "companion_climate_start_mode"), ("number", "target_temperature"), ("sensor", "climate_start_mode")}`.

- [ ] **Step 1: Failing tests** in `tests/test_companion_climate_retired.py`: build each platform's entities for a Companion coordinator and a cloud coordinator, reusing the setup helpers in `tests/test_companion_climate_start_targets.py::test_companion_entry_builds_number_and_select` (the `built` dict fixture around line 170–192 — copy that helper into the new file). Assert:

```python
def test_companion_entry_builds_none_of_the_retired(built_companion):
    names = {type(e).__name__ for ents in built_companion.values() for e in ents}
    assert not names & {
        "VagClimatisationSwitch", "VagWindowHeatingSwitch",
        "VagCompanionClimateModeSelect", "VagCompanionClimateTemperatureNumber",
    }
    assert not [e for e in built_companion["sensor"] if e.entity_description.key == "climate_start_mode"]


def test_cloud_entry_keeps_its_switches(built_cloud):
    names = {type(e).__name__ for e in built_cloud["switch"]}
    assert {"VagClimatisationSwitch", "VagWindowHeatingSwitch"} <= names


def test_registry_entries_of_the_retired_are_removed(hass_registry, built_companion):
    # hass_registry: an entity registry pre-filled with the five companion
    # unique ids (vehicle_unique_id(VIN, key, companion=True)); after setup
    # none of them remains.
    for platform, key in RETIRED_COMPANION_CLIMATE:
        assert hass_registry.async_get_entity_id(
            platform, DOMAIN, vehicle_unique_id(VIN, key, companion=True)
        ) is None


def test_zone_switches_are_controls():
    from custom_components.vag_connect.switch import _COMPANION_CLIMATE_CONTROL_KEYS
    assert {"climate_zone_front_left_switch", "climate_zone_front_right_switch"} <= _COMPANION_CLIMATE_CONTROL_KEYS
```

For `hass_registry`, patch `homeassistant.helpers.entity_registry.async_get` with a `MagicMock` whose `async_get_entity_id` returns an id for the five keys until `async_remove` was called for it (track removals in a set), as `tests/test_companion_entity_twins.py` does for `remove_twin` — copy its fake registry.

- [ ] **Step 2: Run** `python -m pytest -q tests/test_companion_climate_retired.py` — Expected: FAIL.

- [ ] **Step 3: Implement**
  - `companion/entity_twins.py`: add `RETIRED_COMPANION_CLIMATE` (above) and

    ```python
    def drop_retired_climate(hass: HomeAssistant, coordinator: Any, platform: str, vin: str) -> None:
        """Companion: remove the registry entries of climate entities the climate entity replaced."""
        if not coordinator.is_companion():
            return
        for plat, key in RETIRED_COMPANION_CLIMATE:
            if plat == platform:
                remove_twin(hass, plat, vin, key)
    ```
  - `switch.py` `_build_for_vin`: wrap the two appends:

    ```python
        if not coordinator.is_companion():
            if _supported(vin, "command_start_climate"):
                entities.append(VagClimatisationSwitch(coordinator, vin))
            if _supported(vin, "command_start_window_heating"):
                entities.append(VagWindowHeatingSwitch(coordinator, vin))
        else:
            drop_retired_climate(hass, coordinator, "switch", vin)
    ```
    and add `"climate_zone_front_left_switch", "climate_zone_front_right_switch"` to `_COMPANION_CLIMATE_CONTROL_KEYS`.
  - `select.py`: delete the `VagCompanionClimateModeSelect` creation block in `_build_for_vin` and call `drop_retired_climate(hass, coordinator, "select", vin)`; delete the class, `_CLIMATE_START_MODES` and the now-unused imports.
  - `number.py`: where `VagCompanionClimateTemperatureNumber` is appended (line ~257), skip the `target_temperature` description on Companion entries and call `drop_retired_climate(hass, coordinator, "number", vin)`; delete the class, `_HeldTemperatureData`, `_APP_DIAL_KEY` and unused imports.
  - `sensor.py`: in the description loop, `if coordinator.is_companion() and desc.key == "climate_start_mode": remove_twin(hass, "sensor", vin, desc.key); continue`; change `_COMPANION_READ_OF_HELD` to `frozenset({"target_temperature"})` and update its comment ("what the app's dial shows next to the climate entity's held temperature").
  - `companion/client.py` `climate_targets` docstring: "Set by the climate entity (restored across restarts by it)".
  - `companion/entity_twins.py` comment on the window-heating / climatisation twins: "(the climate entity shows the same)".

- [ ] **Step 4: Update old tests**: in `tests/test_companion_climate_start_targets.py` remove tests that construct `VagCompanionClimateTemperatureNumber` / `VagCompanionClimateModeSelect` (Task 1–2 tests cover their behaviour on the climate entity); keep the `ClimateTargets` / client tests. Fix other hits from the grep above.

- [ ] **Step 5: Run full suite + lint**

Run: `python -m pytest -q -p no:cacheprovider tests && ruff check custom_components tests && mypy --ignore-missing-imports --disallow-untyped-defs --disallow-incomplete-defs --warn-return-any custom_components/vag_connect/{climate,switch,select,number,sensor}.py custom_components/vag_connect/companion/entity_twins.py`
Expected: all pass, clean.

- [ ] **Step 6: Commit** `git commit -am "Companion: retire the climate switches, mode select and temperature number"`

### Task 5: Docs and changelog

**Files:**
- Modify: `docs/COMPANION.md`, `docs/COMPANION_CLIMATE.md`, `CHANGELOG.md`, the spec (one correction)

- [ ] **Step 1: `docs/COMPANION.md`**
  - §2.3 Climate table: replace the *Desired Temperature, Desired Climate Start Mode* row and the switch rows with: *Climate Control* — climate (Controls): on/off, temperature, presets *Air conditioning* / *Window heating*; the zone row now says Controls. Remove *Climate Start Mode* from the diagnostic row.
  - §2.4: the held values now live on the climate entity; the window-heating preset is one-shot and returns to *Air conditioning* after a run, as in the app.
  - §2.6 commands table: *Climate Control (climate entity)* replaces "Climate Control, Window Heating switches, climate entity".
  - §3.2 code map: `climate.py` holds `VagCompanionClimate` (presets, restore, one-shot fallback); retired keys in `companion/entity_twins.py`.
  - §3.7 state and persistence: the climate entity restores the held mode and temperature.
- [ ] **Step 2: `docs/COMPANION_CLIMATE.md`** mapping table: running state, window heating and temperature map to the climate entity (preset *Window heating*); add one line under the historical note: "Since the climate rationalisation the select, number and switches are replaced by the climate entity's presets."
- [ ] **Step 3: `CHANGELOG.md`** under `[Unreleased]`:

```markdown
### ⚠️ Breaking — Companion (ADB) climate in one entity

Climate on Companion entries is now run from the climate entity alone: on/off, temperature, and the presets *Air conditioning* and *Window heating*. Window heating is one-shot, as in the app: after a run the preset returns to *Air conditioning*. These entities are removed on Companion entries:

| Removed | Use instead |
|---|---|
| `switch.<car>_adb_climate_control` | climate entity on / off |
| `switch.<car>_adb_window_heating` | preset *Window heating*, then turn on |
| `select.<car>_adb_desired_climate_start_mode` | climate entity preset (while off) |
| `sensor.<car>_adb_climate_start_mode` | climate entity `preset_mode` |
| `number.<car>_adb_desired_temperature` | climate entity temperature |

Automations that start window heating: `climate.set_preset_mode` (*window_heating*), then `climate.turn_on`. The climate zone switches move to Controls. Cloud entries are unchanged.
```

- [ ] **Step 4: Spec correction** in the spec §1 "Kept as separate entities": the climatisation and window-heating binary sensors are not created on Companion entries while the climate entity exists (existing twin rule, `companion/entity_twins.py`); only the Climate ETA sensor stays. Same fix in the spec §3.
- [ ] **Step 5: Commit** `git commit -am "docs: Companion climate in one entity"`

### Task 6: Live check (read-only on the car)

- [ ] After the PR is merged and a release is requested and installed (HACS via HA MCP, then restart): with HA's MCP read the climate entity attributes (`preset_modes`, `preset_mode`, `supported_features`) and confirm the five retired entity ids no longer exist. Do not start climate unless the user asks.
