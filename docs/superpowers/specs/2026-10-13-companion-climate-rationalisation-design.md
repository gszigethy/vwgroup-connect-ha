# Companion climate rationalisation — design

Date: 2026-10-13. Status: approved in brainstorming, spec under review.
Scope: Companion (ADB) entries only. Cloud entries are unchanged.

## Goal

Run climate from one Home Assistant climate entity instead of nine scattered controls, and put every
remaining control in the section it belongs to. This is a deliberate breaking change on Companion entries;
the Companion code is not in upstream yet, so the risk is limited to fork users.

## Background

- The app's *Select mode* picker only chooses what Start will start: air conditioning, or window heating
  only. One Stop ends whichever runs.
- The picker is one-shot: window heating is remembered only once Start is pressed, and after a stop the app
  falls back to air conditioning. Window heating must be chosen deliberately each time.
- *Window heating* (run now) and *Automatic window heating* (the *Autom.* setting, temperature-dependent,
  saved on the car) are different things.
- Home Assistant climate entities (developer docs, `core/entity/climate`): only built-in HVAC modes are
  allowed; custom presets are allowed and are meant for "device options which modify how one or more of the
  modes behave"; `hvac_action` must not be implemented when it cannot be determined; there is no zone
  concept.

## 1. Entity map

**Climate entity** `climate.<car>_adb_climate_control` (Controls):

- HVAC modes `off` / `heat_cool`.
- Target temperature 15.5–30 °C in 0.5 °C steps (15.5 = LO, 30 = HI).
- Presets *Air conditioning* (default) / *Window heating*.
- Current temperature: the outside temperature, as today.

**Removed on Companion entries (breaking):**

| Entity | Replaced by |
|---|---|
| `switch.<car>_adb_climate_control` | climate entity on / off |
| `switch.<car>_adb_window_heating` | preset *Window heating* + turn on |
| `select.<car>_adb_desired_climate_start_mode` | preset while off |
| `sensor.<car>_adb_climate_start_mode` | the climate entity's `preset_mode` |
| `number.<car>_adb_desired_temperature` | the climate entity's target temperature |

**Kept as separate entities, all in Controls:**

| Entity | Why separate | Section |
|---|---|---|
| Climate zone front left / right | no zone concept in HA climate | Configuration → Controls (changes what the next start does) |
| Climate at unlock | car setting | Controls (Codex PR) |
| Automatic window heating | car setting | Controls (Codex PR) |
| Climate ETA sensor | read-only | unchanged |

The climatisation and window-heating binary sensors stay hidden on Companion entries, as today: the
climate entity shows both (existing twin rule in `companion/entity_twins.py`).

Configuration keeps only the *Read …* switches, the sync interval and the three refresh/reset buttons.

## 2. Behaviour

**Preset (mirrors the app).**

- Default *Air conditioning*.
- Choosing *Window heating* while off is stored in HA only: nothing reaches the phone or the car. It survives
  a restart and applies to the next start only.
- When a window-heating run ends (Stop, the car's timer, or the app), the next read sets the preset back to
  *Air conditioning*.
- While running, the preset shows what runs; changing it is refused ("stop climate first").
- The start walk always selects the mode explicitly in the app's picker; it never relies on the app's default.

**Turn on** (`turn_on`, `set_hvac_mode heat_cool`) starts the preset through the existing walks
(`command_start_climate` / `command_start_window_heating`) with every existing check: mode read back before
Start, an unknown mode refuses Start, the battery prompt is never confirmed, request limit and app build
checked.

**Turn off** uses the app's single Stop.

**Temperature.**

- While off: held, applied at the next start, nothing sent.
- While running: the dial moves at once (one car request per gesture); a change over 2 °C is refused.
- `set_temperature` with `hvac_mode`: sets the temperature and starts in one walk.
- With *Window heating*: the temperature is kept but not used for that start.

**Guards.** The request-limit pause, Read-only Mode and the 60 s command gap refuse commands with a clear
error. A preset change while off is local and allowed during a pause. In Read-only Mode the climate entity
is not created, as today.

**State** is always the read-back state: a start the car did not take shows as off.

**Automations** needing window heating: `climate.set_preset_mode` *Window heating*, then `climate.turn_on`
(one car request).

**Out of scope:** `hvac_action`, fan modes, swing modes.

## 3. Code, migration, docs, tests

**Code** (Companion only):

- `climate.py`: new `VagCompanionClimate(VagClimate)`, created on Companion entries instead of the shared
  class, same unique id. It adds the presets, `async_set_preset_mode` and `async_turn_on` / `async_turn_off`
  choosing `async_start_climatisation` or `async_start_window_heating`. It takes over the held temperature
  (from `VagCompanionClimateTemperatureNumber`, `number.py`) and the stored start mode (from
  `VagCompanionClimateModeSelect`, `select.py`, via the client's `store_climate_start_mode`); both are
  restored after a restart.
- The preset falls back to *Air conditioning* when a read shows window heating no longer running after it ran
  or was chosen for the next start.
- Not created on Companion entries: `VagClimatisationSwitch`, `VagWindowHeatingSwitch` (`switch.py`),
  `VagCompanionClimateModeSelect`, `VagCompanionClimateTemperatureNumber`, the Companion's
  `climate_start_mode` sensor. Cloud entries keep them.
- `switch.py`: the two climate-zone keys join the per-key Controls list introduced by the Codex PR.

**Migration.** On setup, a Companion entry removes the five retired entities from the entity registry by
unique id, so they do not linger as unavailable. No repair issue.

**Changelog.** A **⚠️ Breaking** block listing each removed entity and its replacement (the table in §1), and
the window-heating automation recipe.

**Docs.**

- `docs/COMPANION.md` functional design: entity tables (§2.3), dependencies (§2.4: preset, held temperature,
  mirrored fallback), commands table (§2.6).
- `docs/COMPANION.md` technical design: code map (§3.2), state and persistence (§3.7).
- `docs/COMPANION_CLIMATE.md`: mapping table.
- Preset names translated in `strings.json` and all 12 translations.

**Tests.**

- Each preset starts with the right command; a preset change while running is refused.
- A preset change while off sends nothing and survives a restart.
- After a window-heating run the preset returns to *Air conditioning*.
- Temperature: held while off and applied at start; moves the dial while running.
- Request-limit pause and Read-only Mode refuse starts but allow a preset change while off.
- Registry clean-up removes exactly the five entities.
- Cloud entries still get the switches, the select and the number.

## Order

After the Codex PR (charge target, climate at unlock and automatic window heating to Controls), on top of it.
