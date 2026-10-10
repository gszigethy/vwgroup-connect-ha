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

- *Mapped* means the channel reads it as of 4.11.0-6; `#N` is the PR that
  added or changed it.
- *Opt-in* reads run only while their switch on the VW Group Connect
  Settings device is on (Read departure times, Read driving data, …).
- *Not mapped* means it is shown in the app but not read.

Cached navigation readings expire after 24 hours without a successful screen
read. This tolerates temporary navigation failures and long refresh intervals
without keeping yesterday's parking position or warnings available indefinitely.
Affected entities expose `companion_read_at` (UTC), the time the app screen was
read, not when the car last sent data. Expiry adds no navigation, retry or car
request.

## Overview (Vehicle tab)

The overview is read on every poll; no tap is needed. Each tile narrates
itself as `<label>. <value>. <hint>`.

| Tile | Example narration | Field → entity | Keys | Status |
|---|---|---|---|---|
| Range | `Range overview. Battery range: 92 kilometres. Fuel range: 410 kilometres. Open details` | `electric_range_km`, `combustion_range_km` → Electric/Fuel Range | `acc_vehicle_tab_range_tile_value_*` | Mapped |
| Range, charging | `Range overview. Currently charging. Battery range: …` | `is_charging`, `charging_state` | `…_battery_currently_charging` | Mapped; a state, not the whole narration, since #7 |
| Climate control | `Climate control. Off. Open details` (DE `Vorklimatisierung. Aus.`) | `climatisation_active`, `climatisation_state` | `acc_vehicle_tab_clima_tile_label`, `…_all_clima_on/_off` | Mapped by the app's keys (#11); EN/DE regex as fallback |
| Vehicle (lock) | `Vehicle. Locked. Open details` | `doors_locked` → Doors Locked | `acc_vehicle_tab_label_lock_unlock_vehicle`, `…_state_locked/_unlocked` | Mapped by the app's keys (#11); EN/DE regex as fallback |
| Horn and Turn Signals | `Horn and Turn Signals. Open details` | — | — | Not mapped (a command surface; never opened live) |
| Departure times | `Departure times. Open details` | — | — | See Departure times |
| Driving data | `Driving data. Last driven: 3.0 kilometres. Average consumption: 0 litres per 100 kilometres. Open details` | — | `acc_vehicle_tab_label_driving_data` | See Driving data |
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
| Charging method | `Charging method. Immediate charging. Change charging method` | `charge_mode` → Charging Mode (read-only sensor) | Mapped (#13) |
| Start/Stop charging | CTA | `command_start/stop_charging` | Mapped (command) |

## Air Conditioning sheet and Settings (nav reads `climate_detail`, `climate_settings`)

These are covered in [COMPANION_CLIMATE.md](COMPANION_CLIMATE.md):

- **Sheet:** dial, mode, remaining minutes and the window-heating row.
- **Settings:** climate at unlock, window heating, without external power, and
  the zones (driver/passenger front zones on the Tiguan).

Since #6 both screens are read on one walk.

## Vehicle (lock) sheet

On the Tiguan it shows only `Vehicle` / `Locked`: no doors, windows, bonnet or
boot. Nothing beyond the overview tile to read.

### Lock status is read-only (no lock/unlock)

On the companion channel the lock status is a read-only sensor
(`doors_locked`). Lock and unlock commands are deliberately not offered, for
security:

- Unlocking needs the S-PIN. It would have to be typed into the phone over ADB,
  and Home Assistant would have to store it.
- The app's lock control is a slider with no stable handle to target reliably.
- A wrong or misread tap sends the opposite command: unlock instead of lock.
- Repeated attempts risk an S-PIN lockout and spend the car's daily request
  budget.

If your brand's backend supports remote lock, use that channel instead.

## Departure times

Nav read `departure_times` (opt-in, #15). Three timers. Each has a time
(`07:25 AM`), a recurrence (`Weekdays`, `Saturday`) and a `checkable` switch
(all off on the Tiguan). The climate target is in the description (`… chosen
temperature of 22.0°C`). Without timer data the app shows only the section
headers and `departure_timer_subscreen_climadeactivated_footer`. The charging
section needs charging locations set in the car; its preferred charging times
go with the charge mode *Charge at preferred times*.

| Value | Field → entity | Status |
|---|---|---|
| Timer on/off | `departure_timer_N_enabled` → Departure Timer N Enabled | Read from the switch's `checked` state (#15); unknown when not read (#10) |
| Timer time | `departure_timer_N_time` | 24-hour `HH:MM` (#15) |
| Enabled count | `departure_timer_enabled_count` | When all three rows are on screen (#15) |
| Weekdays | `departure_timer_N_weekdays` | From the timer's page (`cta_monday` … `cta_sunday`), app 4.6.4 |
| Repeat | `departure_timer_N_repeat` | From the timer's page (`cta_repeat`), app 4.6.4 |

Writes (VW, app 4.6.4; the switch also on 4.3.2), all through
`command_set_departure_timer`:

- **Departure Timer N** switch: taps the row's switch, which the app sends at
  once, and watches it for a flip back.
- **Departure Timer N — Time** entity and the `set_departure_timer` service: set
  the time, weekdays and Repeat on the timer's page one read-back tap at a
  time, then Save (one request). The app's Save switches the timer on, so an
  edit with `enabled: false` is refused; `enabled` may be left out. The
  service refuses `charging`, `climatisation` and `target_soc_pct`, and maps
  `one_off_day` (today to six days ahead) to a one-time timer on that weekday.
- A write needs all three rows read. A page edit also needs the timer's time
  to differ from the other two (the page shows no timer number), and the
  opened page's time must match its row. Anything unexpected before Save
  cancels the page; nothing is sent.

## Driving data

Nav read `driving_data` (opt-in, #16). The trip cards sit in a sideways
carousel; the second is drawn clipped (labels, no values) until one sideways
swipe.

| Card | Values | Fields | Status |
|---|---|---|---|
| Last single trip | date, time, distance, consumption (kWh/100 km and l/100 km), average speed, driving time | `last_trip_*` | Mapped (#16), not date/time |
| From charging or refuelling | the same set | `refuel_trip_*` | Mapped (#16), not date/time |
| Last long-haul trip | the same set | — | Not mapped |
| Month | average consumption | — | Not mapped |

Keys: `volkswagen_acc_cat_snowshoe_rts_*` labels and `volkswagen_cat_snowshoe_rts_unit*`
units; durations by `duration_hours` / `duration_minutes`.

## Vehicle Health Report (nav read `vehicle_health`)

| Row | Tiguan | Golf GTE (mi) | Field → entity | Key | Status |
|---|---|---|---|---|---|
| Total distance | `322 km` | `22,015 mi` | `odometer_km` → Odometer | `screen_vehiclehealth_subhead_totaldistance` | Mapped by key (#8) |
| Next service | `711 days / 29,700 km` | `71 days / 12,100 mi` | `service_due_in_days`, `service_km` | `…_subhead_nextinspection` | Mapped, days and distance (#8) |
| Next oil service | — | `71 days / 1,500 mi` | `oil_service_due_in_days`, `oil_service_km` | `…_subhead_oil_service` | Mapped, days and distance (#8) |
| AdBlue range | — | — | `adblue_range_km` | `…_subhead_adblue_level` | Mapped (#8), no dump yet |
| Warning header and categories | `No issues found` + 7 categories | same | `warning_active`, `warning_count`, `warning_messages` | `screen_vehiclehealth_overview_*` | Mapped (#14); a warning layout not seen live yet |

## Vehicle Settings (nav read `vehicle_settings`)

| Row | Tiguan | Field → entity | Key | Status |
|---|---|---|---|---|
| Charging up to (50–100 %) | `80%` | `target_soc` + Charge Target number | — | Mapped (read and set) |
| Reduced AC charging current | off | — (`vw_eu` has amps, not on/off) | `vehiclesettingsscreen_reducedchargingspeed` | Not mapped |
| Automatically release AC connector | on | `auto_unlock_when_charged` → binary sensor | `vehiclesettingsscreen_automaticplugunlock` | Mapped (#9) |
| Synchronise now | button | `command_sync_vehicle` → App sync interval number, Force vehicle refresh button | — | Mapped (command); the button syncs once, then re-reads the app after 3 minutes |
| Plug & Charge, users, notifications, contracts | links | — | — | Not mapped (account) |

## Other tabs

| Screen | Notes |
|---|---|
| Navigation tab | Map, find vehicle, parking marker, share (nav read `parking_position` → latitude/longitude). |
| Profile tab | Account, app settings, help, We Charge, wallbox, roadside assistance. Not read. |
| Authorised workshop, Digital extras | Text and offers. Not read. |

The **Read parking position** switch opts into opening Map, Find vehicle, the
parking marker and Share to read the coordinate preview; nothing is shared.
On app 4.6.4, this walk also taps **Agree** if the Google Maps consent appears,
only while that switch is on. Other reads and commands press BACK without
agreeing and stop that attempt, even if BACK reveals the overview. A missing
Agree button makes the walk back out and stop. Consent that remains after the
bounded dismissal attempts also stops the walk.

## Other brands in the #968 dumps

| Car | Overview read today | Detail screens |
|---|---|---|
| CUPRA Born (WEZANGO) | SoC 51, range 182, locked, ignition | Battery, max charge, battery management, climate, doors/lights captured; the CUPRA preset has no nav reads. |
| e-Up!, ID.4 (kgroshert, DE) | range, charging, locked, climate *Aus* | Charge sheet: SoC, target 90, 10 kW, remaining time; climate sheet. |
| Golf GTE Mk8 (plainmad, mi) | range (mi → km), charging, locked, climate on/off | Charge, climate (idle and active), health. |

## Stale entities on the companion entry

Three registered entities nothing in the current companion code fed were
removed from the HA registry on 2026-10-06: `sensor.<car>_vehicle_requests`
(left from the dropped betas), `sensor.<car>_vehicle_status`
(`vehicle_state`) and `binary_sensor.<car>_rear_window_heating`
(`window_heating_back`).

## Decisions (resolved 2026-10-06)

- **D1, departure times:** a new opt-in nav read (#15).
- **D2, charge mode:** read into `charge_mode` with a read-only sensor (#13).
  In the APK the charging method is set per charging location; *Charge at
  preferred times* charges only inside that location's preferred times,
  which are set in the infotainment.
- **D3, driving data:** a new opt-in nav read (#16).
- **D4, health warnings:** read into the warning fields (#14).
- **D5, stale entities:** removed.
