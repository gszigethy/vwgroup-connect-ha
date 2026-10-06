# Volkswagen app map for the ADB Companion

A screen-by-screen map of the Volkswagen app (`com.volkswagen.weconnect` 4.3.2)
as the Companion channel sees it: what each screen shows, how the channel reaches
it, which app string keys identify it, and which Home Assistant field it feeds.

Sources:

- A live, read-only walkthrough of a Tiguan Life 1.5 l eHybrid on 2026-10-06
  (English app). Only navigation was tapped; nothing that acts on the car.
- The 2026-10-02 capture set of the same car (58 screens).
- Every dump attached to upstream issue #968:
  - WEZANGO: CUPRA Born, 8 screens.
  - kgroshert: e-Up! and ID.4, German, 8 screens.
  - plainmad: Golf GTE Mk8 on imperial units, 11 screens.
- String keys come from the 4.3.2 APK's `resources.arsc`.

**Rule for every mapping:** a companion value goes into the field the VW cloud
parser (`cariad/api/vw_eu.py`) fills for the same value, never into a field only
the EU Data Act portal fills.

**Reading this table:**

- *Mapped* means the channel reads it today.
- *PR* means an open PR adds it.
- *Decision* means it waits on a choice listed at the end.
- *Not mapped* means it is shown in the app but not read.

## Overview (Vehicle tab)

The overview is read on every poll; no tap is needed. Each tile narrates
itself as `<label>. <value>. <hint>`.

| Tile | Example narration | Field → entity | Keys | Status |
|---|---|---|---|---|
| Range | `Range overview. Battery range: 92 kilometres. Fuel range: 410 kilometres. Open details` | `electric_range_km`, `combustion_range_km` → Electric/Fuel Range | `acc_vehicle_tab_range_tile_value_*` | Mapped |
| Range, charging | `Range overview. Currently charging. Battery range: …` | `is_charging`, `charging_state` | `…_battery_currently_charging` | Mapped; the state was the whole narration until PR #7 |
| Climate control | `Climate control. Off. Open details` (DE `Vorklimatisierung. Aus.`) | `climatisation_active`, `climatisation_state` | `acc_vehicle_tab_clima_tile_label`, `…_all_clima_on/_off` | Mapped by EN/DE regex; by keys in PR #11 |
| Vehicle (lock) | `Vehicle. Locked. Open details` | `doors_locked` → Doors Locked | `acc_vehicle_tab_label_lock_unlock_vehicle`, `…_state_locked/_unlocked` | Mapped by EN/DE regex; by keys in PR #11 |
| Horn and Turn Signals | `Horn and Turn Signals. Open details` | — | — | Not mapped (a command surface; never opened live) |
| Departure times | `Departure times. Open details` | — | — | See Departure times |
| Driving data | `Driving data. Last driven: 3.0 kilometres. Average consumption: 0 litres per 100 kilometres. Open details` | — | `acc_vehicle_tab_value_driving_data_distance_consumption_km/_miles` | Decision D3 |
| Vehicle Health Report | `Vehicle Health Report. Open details` | — | — | See Vehicle Health Report |
| Your vehicle | `Your vehicle: <model>. Synchronised 4 hours 4 minutes ago` | `companion_app_synced_at` → Last vehicle sync | `SYNC_*` | Mapped |

`binary_sensor.<car>_doors_locked` showing **off** while the app says *Locked*
is correct. It uses HA's LOCK device class, where off means locked.

## Range sheet (nav read `charge_detail`)

Tap the range tile; close with *Close sheet*.

| Row | Example | Field → entity | Status |
|---|---|---|---|
| `rangeArcBatterySoc` | `Charging status. Battery charge level: 83 per cent. Target charge level reached` | `battery_soc`, `charging_state`, `is_charging` | Mapped |
| Charging details | `Charging details. Target charge level: 80 per cent` | `target_soc` | Mapped |
| Power, speed, time | ID.4: 10 kW, 270 min | `charging_power_kw`, `charging_rate_kmh`, `remaining_charge_time_min` | Mapped |
| Charging method | `Charging method. Immediate charging. Change charging method` | `vw_eu` field `charge_mode` | Decision D2 |
| Start/Stop charging | CTA | `command_start/stop_charging` | Mapped (command) |

## Air Conditioning sheet and Settings (nav reads `climate_detail`, `climate_settings`)

These are covered in [COMPANION_CLIMATE.md](COMPANION_CLIMATE.md):

- **Sheet:** dial, mode, remaining minutes and the window-heating row.
- **Settings:** climate at unlock, window heating, without external power, and
  the zones (driver/passenger front zones on the Tiguan).

Since PR #6 both screens are read on one walk.

## Vehicle (lock) sheet

On the Tiguan it shows only `Vehicle` / `Locked`: no doors, windows, bonnet or
boot. Nothing beyond the overview tile to read.

## Departure times

Three timers. Each has a time (`07:25 AM`), a recurrence (`Weekdays`,
`Saturday`) and a `checkable` switch (all off on the Tiguan). The climate
target is in the description (`… chosen temperature of 22.0°C`). The charging
section needs charging locations set in the car.

| Value | Field → entity | Status |
|---|---|---|
| Timer on/off | `departure_timer_N_enabled` → Departure Timer N Enabled | Shown as *off* from the model default without being read; PR #10 makes them unknown. Reading them: Decision D1 |
| Timer time | `departure_timer_N_time` | Decision D1 |

## Driving data

| Section | Values |
|---|---|
| Last single trip | date, time, distance, consumption (kWh/100 km and l/100 km), average speed, driving time |
| From charging or refuelling | the same set |
| Month | average consumption |

Keys: `volkswagen_acc_cat_snowshoe_rts_*` (`distanceDrivenLabel`,
`averageSpeedLabel`, `drivingTimeLabel`, `lastSingleTripLabel`). The `vw_eu`
fields `last_trip_*` and `refuel_trip_*` exist. Decision D3.

## Vehicle Health Report (nav read `vehicle_health`)

| Row | Tiguan | Golf GTE (mi) | Field → entity | Key | Status |
|---|---|---|---|---|---|
| Total distance | `322 km` | `22,015 mi` | `odometer_km` → Odometer | `screen_vehiclehealth_subhead_totaldistance` | Mapped; by key in PR #8 |
| Next service | `711 days / 29,700 km` | `71 days / 12,100 mi` | `service_due_in_days`, `service_km` | `…_subhead_nextinspection` | Days mapped; distance in PR #8 |
| Next oil service | — | `71 days / 1,500 mi` | `oil_service_due_in_days`, `oil_service_km` | `…_subhead_oil_service` | Days mapped; distance in PR #8 |
| AdBlue range | — | — | `adblue_range_km` | `…_subhead_adblue_level` | PR #8 (no dump yet) |
| Warning categories | `No issues found` + 7 categories | same | — | `screen_vehiclehealth_overview_*` | Decision D4 |

## Vehicle Settings (nav read `vehicle_settings`)

| Row | Tiguan | Field → entity | Key | Status |
|---|---|---|---|---|
| Charging up to (50–100 %) | `80%` | `target_soc` + Charge Target number | — | Mapped (read and set) |
| Reduced AC charging current | off | — (`vw_eu` has amps, not on/off) | `vehiclesettingsscreen_reducedchargingspeed` | Not mapped |
| Automatically release AC connector | on | `auto_unlock_when_charged` → binary sensor | `vehiclesettingsscreen_automaticplugunlock` | PR #9 |
| Synchronise now | button | `command_sync_vehicle` | — | Mapped (command) |
| Plug & Charge, users, notifications, contracts | links | — | — | Not mapped (account) |

## Other tabs

| Screen | Notes |
|---|---|
| Navigation tab | Map, find vehicle, parking marker, share (nav read `parking_position` → latitude/longitude). |
| Profile tab | Account, app settings, help, We Charge, wallbox, roadside assistance. Not read. |
| Authorised workshop, Digital extras | Text and offers. Not read. |

## Other brands in the #968 dumps

| Car | Overview read today | Detail screens |
|---|---|---|
| CUPRA Born (WEZANGO) | SoC 51, range 182, locked, ignition | Battery, max charge, battery management, climate, doors/lights captured; the CUPRA preset has no nav reads. |
| e-Up!, ID.4 (kgroshert, DE) | range, charging, locked, climate *Aus* | Charge sheet: SoC, target 90, 10 kW, remaining time; climate sheet. |
| Golf GTE Mk8 (plainmad, mi) | range (mi → km), charging, locked, climate on/off | Charge, climate (idle and active), health. |

## Stale entities on the companion entry

These are registered but nothing in the current companion code feeds them:

- `sensor.<car>_vehicle_requests`: the key no longer exists in the code (left
  from the dropped betas).
- `sensor.<car>_vehicle_status` (`vehicle_state`).
- `binary_sensor.<car>_rear_window_heating` (`window_heating_back`).

## Decisions

- **D1, departure times:** read the three timers (switch state and time) from the Departure times screen as
  a new opt-in nav read, or leave them hidden (PR #10).
- **D2, charge mode:** the `vw_eu` field `charge_mode` only feeds the charge-mode select, which needs a command
  the companion lacks. Reading it shows nothing unless a read-only charge-mode sensor is added.
- **D3, driving data:** a new opt-in nav read for last trip / since refuel into `last_trip_*` / `refuel_trip_*`.
- **D4, health warnings:** *No issues found* vs *Issues found* (+ which category) as a sensor.
- **D5, stale entities:** remove the three stale registry entries above.
