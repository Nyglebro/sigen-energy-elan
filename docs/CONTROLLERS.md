# Reading Innovo Energy from a controller

Controllers should read **Home Assistant**, never the solar equipment
directly (a SolarEdge inverter, for one, accepts only one Modbus TCP client and
Home Assistant holds it). The entity ids below are the same for every brand.

## Access

Create a long-lived access token in HA (Profile → Security) and use the REST API:

```
GET  /api/states/<entity_id>                       # read one value
GET  /api/states                                   # read all (filter by entity_id)
POST /api/services/number/set_value                # change a setting
     {"entity_id": "number.energy_solar_panel_watts", "value": 400}
POST /api/services/innovo_energy/provision_dashboards   # rebuild dashboards
```

For a push feed instead of polling, subscribe to `state_changed` over the HA
WebSocket API.

Live values update whenever the brand's integration reports (SolarEdge: set its
polling interval to 10–15 s; Enphase: about every minute, the Envoy's own rate).

## Entity ids

New installs create these ids. If an id is taken or renamed on a site, find the
entity on the *Innovo Energy* device of the `innovo_energy` integration.

Every entity shows a value, or:

| State | Meaning | Controller |
|---|---|---|
| `NA` | the site's equipment doesn't have this reading at all (no grid meter, no battery, no DC side on Enphase). No unit; attribute `supported: false`. Decided from the equipment at start-up, never from a missing value. | leave the input out |
| `unknown` | the equipment has it, but there is no value right now (not reported yet, asleep, offline, setting not entered) | show `—` |
| `unavailable` | Home Assistant's own: the integration isn't running | keep the last value, retry |

Binary sensors can't show `NA` (Home Assistant allows only on, off, unknown):
for them the attribute `supported: false` is the signal.

### Live

| Entity | Unit | Meaning |
|---|---|---|
| `sensor.energy_solar_power` | W | Solar production now (estimated with SoE-only batteries) |
| `sensor.energy_house_power` | W | House consumption now |
| `sensor.energy_grid_power` | W | **+ buying**, − selling |
| `sensor.energy_battery_power` | W | **+ charging**, − discharging (estimated with SoE-only batteries) |
| `sensor.energy_battery_level` | % | Battery state of energy |
| `sensor.energy_battery_state` | text | `Charging` / `Discharging` / `Full` / `Idle` |
| `sensor.energy_grid_state` | text | `Importing` / `Exporting` / `Balanced` / `Outage` |
| `sensor.energy_solar_share_now` | % | Share of the house not supplied by the grid |
| `sensor.energy_inverter_status` | text | `Producing` / `Sleeping` / `Offline` / `Fault <code>` |
| `binary_sensor.energy_grid_connected` | on/off | `on` = connected to the utility, `off` = grid outage |

### Today (reset at local midnight)

| Entity | Unit |
|---|---|
| `sensor.energy_solar_today` | kWh |
| `sensor.energy_house_today` | kWh |
| `sensor.energy_grid_import_today` | kWh |
| `sensor.energy_grid_export_today` | kWh |
| `sensor.energy_battery_charged_today` | kWh |
| `sensor.energy_battery_discharged_today` | kWh |
| `sensor.energy_self_sufficiency_today` | % |
| `sensor.energy_grid_cost_today` | $ (exports credited at the same price) |

### Performance

| Entity | Unit | Meaning |
|---|---|---|
| `sensor.energy_solar_typical_today` | kWh | Typical output for this site, array size and date |
| `sensor.energy_solar_today_vs_typical` | % | Today's progress vs typical |
| `sensor.energy_solar_7_day_average` | kWh | |
| `sensor.energy_solar_vs_typical` | % | Last 7 days vs typical (includes cloudy days) |
| `sensor.energy_solar_efficiency_spec` | % | Best 3 of last 7 days vs typical; ~100–115 % is healthy |
| `sensor.energy_solar_efficiency_history` | % | Best 3 of last 7 days vs the system's own season-adjusted best |
| `sensor.energy_solar_health_trend` | text | `Learning` / `Improving` / `Stable` / `Declining` (attribute `change_pct`) |
| `sensor.energy_solar_cleaning_recommended` | text | `Learning` / `Yes` / `No` |
| `sensor.energy_solar_best_day`, `sensor.energy_solar_best_day_date` | kWh, date | |
| `sensor.energy_solar_yesterday`, `sensor.energy_house_yesterday` | kWh | |
| `sensor.energy_solar_lifetime_daily_average` | kWh | Needs the commissioning date |
| `sensor.energy_solar_array_size` | kW | Panel count × panel watts |
| `sensor.energy_daily_history` | days | Attribute `days`: `[date, solar, house, import, export]` |

"Learning" means fewer than 10 days of history (health trend: until there are
prior weeks to compare).

### Electricity rates

| Entity | Meaning |
|---|---|
| `sensor.energy_price_now` | Import price now ($/kWh); attribute `tier` for tiered plans |
| `sensor.energy_export_price_now` | Export credit now ($/kWh) |
| `sensor.energy_price_period` | Period name from the plan (e.g. `On-peak`) or `Override` |
| `sensor.energy_next_price_change` | Timestamp of the next change; attributes `next_price`, `next_period` |
| `sensor.energy_tariff` | Plan name (attributes: seasons, currency, source, export credit) |
| `select.energy_tariff_source` | `Rate plan` or `Price sensor` (the sensor chosen in the options) |
| `select.energy_export_credit` | `Same as import` / `Fixed rate` / `No credit` |
| `number.energy_export_rate` | Fixed export rate |
| `number.energy_price_override` | Price override; anything above 0 wins over everything else, 0 turns it off |

Set a whole plan:

```
POST /api/services/innovo_energy/set_tariff
{"plan": {
  "name": "TOU 4-9", "currency": "USD", "tier_period": "month",
  "seasons": [
    {"name": "Summer", "months": [6, 7, 8, 9],
     "weekday": [["00:00", 0.40, "Off-peak"], ["16:00", 0.64, "On-peak"], ["21:00", 0.40, "Off-peak"]],
     "weekend": [["00:00", 0.40, "Off-peak"], ["16:00", 0.52, "Mid-peak"], ["21:00", 0.40, "Off-peak"]]},
    {"name": "Winter", "months": [1, 2, 3, 4, 5, 10, 11, 12],
     "weekday": [["00:00", 0.38, "Off-peak"], ["08:00", 0.34, "Super off-peak"],
                 ["16:00", 0.50, "Mid-peak"], ["21:00", 0.38, "Off-peak"]]}
  ]}}
```

Rows start at a time and run until the next row; each day starts at `00:00`;
seasons must cover all 12 months; a missing `weekend` reuses the weekday rows.
A rate can be tiered: `[{"upto": 40, "rate": 0.07065}, {"rate": 0.11142}]`, where
`upto` counts kWh of grid import per `tier_period` (`day` or calendar `month`).
Holidays are treated as normal days.

Change prices by period name (e.g. after a rate change):

```
POST /api/services/innovo_energy/set_tariff_rates
{"rates": {"On-peak": 0.66, "Off-peak": 0.41}, "season": "Summer"}
```

Temporary override (e.g. a critical-peak event), then clear it:

```
POST /api/services/number/set_value {"entity_id": "number.energy_price_override", "value": 1.20}
POST /api/services/number/set_value {"entity_id": "number.energy_price_override", "value": 0}
```

### Running totals (kWh, never reset)

`sensor.solar_pv_production_energy`, `sensor.battery_charged_energy`,
`sensor.battery_discharged_energy`.

### Settings (writable)

`number.energy_solar_panel_count`, `number.energy_solar_panel_watts`,
`number.energy_solar_array_tilt`, `number.energy_solar_array_azimuth`
(180 = south), `number.energy_battery_capacity` (kWh), `number.energy_battery_reserve` (%),
`date.energy_solar_commissioned`, and `button.energy_provision_dashboards`.

### Equipment readings

The same names for every brand. On a site without the equipment for a reading
it is `NA` (see above).

| Entity | Unit | SolarEdge | Enphase |
|---|---|---|---|
| `sensor.energy_solar_produced_lifetime` | kWh | inverter | all Envoys |
| `sensor.energy_grid_imported_lifetime`, `sensor.energy_grid_exported_lifetime` | kWh | grid meter | grid CT |
| `sensor.energy_grid_voltage_l1`, `_l2` | V | grid meter | grid CT |
| `sensor.energy_grid_current_l1`, `_l2` | A | grid meter | grid CT |
| `sensor.energy_inverter_ac_power` | W | inverter | all Envoys' production |
| `sensor.energy_inverter_ac_voltage` | V | inverter | production CT |
| `sensor.energy_inverter_ac_current` | A | inverter | production CT |
| `sensor.energy_inverter_ac_frequency` | Hz | inverter | production CT |
| `sensor.energy_dc_power`, `sensor.energy_dc_voltage`, `sensor.energy_dc_current` | W, V, A | inverter | `NA` (microinverters) |
| `sensor.energy_inverter_temperature` | °C / °F | inverter heat sink | `NA` |
| `binary_sensor.energy_grid_connected` | on/off | inverter | IQ Meter Collar / System Controller |

Inverter AC and DC power can read slightly negative at night (standby draw).

### Screens

Image entities `image.energy_screen_<page>` (and `image.energy_dashboard_image`
for the live page), 720 × 720 PNG, redrawn every minute. The page list is in the
attribute `image_entities` of `sensor.energy_dashboard_image_url`. On a Magic Cube
Aura every page is also a plain file at `http://<aura>/icons/solar/` in five
shapes, two sizes, JPG and PNG; `screens.json` there lists what exists.

The brand's own entities (`sensor.solaredge_*`, `sensor.envoy_*`, …) remain
available for detail views, but differ per brand.
