# Setting up a new site

A checklist for installing Innovo Energy on a new Home Assistant system, built
from real installs. Work through it top to bottom; most problems on past sites
came from one of these steps being skipped.

## 1. Before you start

| Check | Why |
|---|---|
| The brand's integration is installed and shows live values | Innovo Energy only reads it. SolarEdge: [Innovo Solar Edge](https://github.com/InnovoDeveloper/innovo-solar-edge) (its README has the inverter checklist: Modbus TCP, one client only, the RS485 device list). Enphase: Home Assistant's Enphase Envoy integration, added once for **every** Envoy on the site. |
| Each inverter / Envoy has a DHCP reservation | The brand integration connects by IP address. |
| Home Assistant's home location, time zone and currency are set: Settings → System → General | The sun position and the typical-output lookup (NREL PVWatts) use the location. A location of 0, 0 is flagged as a repair; a wrong time zone shifts every daily total. |

## 2. Install and configure

1. Install through HACS (see the [README](../README.md#install)) and restart.
2. Add **Innovo Energy** and pick the data source.
   - **Enphase**: the Envoy with the grid meter (net-consumption CT) is
     pre-selected. With several Envoys, choose how the other Envoys' arrays are
     wired: *behind the main grid meter* (they feed the house panel; the usual
     case) or *separate*. Leave *Turn on the Envoy's per-leg voltage and current*
     ticked: Innovo Energy switches on the Envoy readings it needs (they ship
     disabled).
3. **Configure → Settings**:
   - **This system has a battery**: untick on sites without one.
   - **Electricity price sensor**: optional, if prices come from another
     integration.
   - **PVWatts lookup**: turn off only if the home location must not be sent to
     NREL (typical/spec metrics are then unavailable).

The energy model and dashboards then set themselves up. About a minute after the
first readings, Innovo Energy fills in whatever the site doesn't have yet: the
HA Energy dashboard sources and a **Solar & Energy** dashboard. Existing
dashboards are not overwritten. On a Magic Cube Aura the screens are published
to `http://<aura>/icons/solar/` automatically.

## 3. What each kind of site gets

Innovo Energy detects the equipment and adapts the entities, dashboards and
screens. Nothing needs to be selected by hand except the battery setting.

| Site | Live and today | Money | Dashboards and screens |
|---|---|---|---|
| **Solar only** (no grid meter, no battery) | Solar power and production, typical output, efficiency | **Solar value**: each kWh valued at the rate in force when it was produced | Solar-only versions; grid and home values are `NA` |
| **Solar + grid meter** | + home use, grid import/export, self-sufficiency | + grid cost and savings | Full energy flow |
| **Solar + meter + battery** | + battery power, charge, time to full or reserve | + savings from the battery | Full energy flow with battery |
| **Per-panel data** (Enphase microinverters) | + output of every panel | | + the Panels screen; panels well below the others or not reporting show on System Health |

Home use, grid figures and costs need a **grid meter** (CTs on the main feed:
a SolarEdge energy meter, or the Envoy's consumption CTs). The inverter alone
only measures what the panels produce. If a client wants costs and
self-sufficiency, quote the meter.

## 4. Panel settings: enter them and check them

Set these on the **Innovo Energy** device (or the *System settings* card of the
Solar & Energy dashboard):

| Setting | Where to find the real value |
|---|---|
| **Solar Panel Count** | SolarEdge: the optimizer count in the monitoring portal or SetApp. Enphase: the microinverter count (one per panel). |
| **Solar Panel Watts** | The panel model's datasheet or label (typically 350–500 W) |
| **Tilt** / **Azimuth** | Roof pitch in degrees; direction the panels face (180 = south, 270 = west) |
| **Commissioned** | Install date; used for the lifetime daily average |

Typical output, efficiency, health and the cleaning indicator all depend on
these numbers, so check them against what the equipment measures:

- **The array must be rated above the highest DC input ever measured**
  (SolarEdge). Innovo Energy remembers that peak (attribute `peak_dc_input_kw` on
  *Solar Array Size*). If the settings are smaller, a repair explains it and gives
  the likely minimum. On a clear day the DC input rarely exceeds about 80% of the
  array rating, so the array is at least `peak ÷ 0.8`.
- **Settings more than twice the inverter's rating** are flagged too. That
  usually means the array total was typed as the watts per panel.
- **Lifetime energy cross-check.** The lifetime production divided by the years
  since install and by the site's yearly yield per kW gives a rough array size.
  Yearly yield is roughly 1,100–1,300 kWh per kW in southern Canada and the
  northern US, 1,500–1,800 in California and 1,800–2,000 in Arizona;
  [PVWatts](https://pvwatts.nrel.gov) gives the figure for an address.
- **After a few full days**, *Efficiency vs spec* should sit around 95–115%.
  Far outside that, the settings (or the panels) need a look.

## 5. Electricity rates

Choose where prices come from (*Tariff Source*):

- **Rate plan**: enter the utility's time-of-use plan under Configure →
  *Electricity rate plan*, or send it as JSON with `innovo_energy.set_tariff`.
- **Price sensor**: take the price from another integration or a template
  sensor ($/kWh).
- **Price override**: a number entity that a controller can set directly;
  0 = off. It takes precedence over everything else.

Example plan: Ontario time-of-use (OEB rates for November 2025 to October
2026). Ontario rates change every November 1; update them when the OEB
publishes new ones.

```json
{
  "name": "Ontario Time-of-Use (OEB, Nov 2025 - Oct 2026)",
  "currency": "CAD",
  "tier_period": "month",
  "seasons": [
    {"name": "Winter", "months": [11, 12, 1, 2, 3, 4],
     "weekday": [["00:00", 0.098, "Off-peak"], ["07:00", 0.203, "On-peak"],
                 ["11:00", 0.157, "Mid-peak"], ["17:00", 0.203, "On-peak"],
                 ["19:00", 0.098, "Off-peak"]],
     "weekend": [["00:00", 0.098, "Off-peak"]]},
    {"name": "Summer", "months": [5, 6, 7, 8, 9, 10],
     "weekday": [["00:00", 0.098, "Off-peak"], ["07:00", 0.157, "Mid-peak"],
                 ["11:00", 0.203, "On-peak"], ["17:00", 0.157, "Mid-peak"],
                 ["19:00", 0.098, "Off-peak"]],
     "weekend": [["00:00", 0.098, "Off-peak"]]}
  ]
}
```

Each row starts at its time and runs until the next one. Weekend rows default
to the weekday rows if left out. Tiered rates, export credit and setting prices
over the API are described in [CONTROLLERS.md](CONTROLLERS.md).

## 6. Dashboards and screens

- **Rebuild the Solar & Energy dashboard** after changing equipment (adding a
  meter or battery) or updating the integration: press *Provision Dashboards* on
  the Innovo Energy device, or call `innovo_energy.provision_dashboards`. This
  overwrites that one dashboard; the Energy dashboard keeps its other sources
  (water, gas, devices).
- **Screens for controllers**: on a Magic Cube Aura they are at
  `http://<aura>/icons/solar/` in five shapes, two sizes, JPG and (with the PNG
  option) see-through PNG; the viewer page there copies addresses and designs
  looks. They are also image entities. See [CONTROLLERS.md](CONTROLLERS.md).
- A screen shows "Please come back again later…" until it has data. *Solar
  Health* and *Week* need the first full day.

## 7. Battery sites

- **Backup reserve**: the share of the battery held back for outages. Enphase
  sites use the reserve set in the Envoy; SolarEdge sites the *Battery Reserve*
  setting on the Innovo Energy device.
- **SolarEdge storage profile reverts**: if the battery profile keeps reverting
  after reconnecting, it is being pushed from the SolarEdge monitoring account.
  Change it there or ask SolarEdge support; local changes are overwritten.
- The battery's usable capacity defaults to its nameplate. Adjust *Battery
  usable capacity* if the battery reports differently.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "No supported solar integration was found" | The brand's integration isn't set up or isn't running | Set it up first (step 1), then add Innovo Energy |
| All values `unknown` | The brand's integration has no data | Check its device in Settings → Devices & services (equipment offline, IP changed) |
| A value is `NA` | The site's equipment doesn't have that reading | Correct; controllers leave it out |
| Typical output or efficiency empty | Location not set, or PVWatts unreachable | Set the location; the lookup retries every 6 h |
| Efficiency far from 100% | Panel settings wrong | See step 4 |
| Enphase: home use too high or too low | Several Envoys, arrays wiring set wrong | Configure → Settings → *Other Envoys' arrays* |
| Solar & Energy dashboard missing cards after an update | It is only built once | Press *Provision Dashboards* |
