# Sigen Energy for ELAN

Experimental Home Assistant integration for **Sigenergy ESS → Magic Cube → ELAN Solar Pro**. Derived from [Innovo Energy 1.2.2](https://github.com/InnovoDeveloper/innovo-energy), with a native Sigenergy source and its own HACS identity.

**Version 0.2.0 — experimental, not yet validated on a live Cube/ELAN installation.** Target: [Sigenergy ESS 1.2.7.5](https://github.com/TypQxQ/Sigenergy-Local-Modbus/tree/v.1.2.7.5), one inverter, single-phase L/N. Both integrations must run on the same Home Assistant. No ELAN Driver Studio is required.

## Install using HACS

1. Back up Home Assistant.
2. If the upstream Innovo Energy HACS download is installed, remove its configured entry and HACS download first, then restart. If an **Innovo Energy** integration entry is configured, back up its settings/history and remove that entry under **Settings → Devices & services** before setting up this integration. Both integrations use the common energy entity names and solar image folder. Merely disabling an entry can leave its entity names reserved. Keep Sigenergy ESS installed and running.
3. In **HACS → menu → Custom repositories**, add `https://github.com/Nyglebro/sigen-energy-elan`, category **Integration**.
4. Find **Sigen Energy for ELAN**, download it, and restart Home Assistant.
5. **Settings → Devices & services → Add integration → Sigen Energy for ELAN**. Select your Sigenergy source.
6. Enter panel count, watts, tilt/direction, battery settings and electricity tariff. Check the Home Assistant location/time zone. On the Cube, verify that the existing solar image publication folder is selected automatically.
7. Compare the five live readings below with Sigenergy. Then open the Cube's `/icons/solar/` viewer and check your existing ELAN Magic Cube Solar Pro pages.

This installs to `custom_components/innovo_energy`, replacing the original Innovo Energy code. The HACS repository and display name remain Sigen Energy for ELAN. Keep Sigenergy ESS (`sigen`) installed. Do not install/update the upstream Innovo Energy HACS repository alongside this fork: they use the same component directory.

## Upgrade from 0.1.0 / 0.1.1 (required for ELAN discovery)

The supplied Solar Pro driver confirms that discovery filters on the integration domain. Renaming the device in 0.1.1 could not fix this. Version 0.2.0 restores `innovo_energy` internally while retaining the separate repository and display name.

1. Make a full HA backup and record your panel, battery, tariff and image publication settings.
2. Before downloading 0.2.0, remove the **Sigen Energy for ELAN** entry in **Settings → Devices & services**. Keep **Sigenergy ESS** running.
3. Remove the old **Sigen Energy for ELAN** download in HACS and restart HA. If upstream **Innovo Energy** is still downloaded in HACS, remove that download too; the two repositories cannot manage the same directory.
4. Remove/re-add this custom repository in HACS if needed to refresh its component folder, then download **Sigen Energy for ELAN 0.2.0** (main/default branch) and restart HA.
5. Add **Sigen Energy for ELAN** again in Devices & services, select the Sigenergy source, and restore your settings. Confirm the common `sensor.energy_*` readings and solar images work.
6. Press **Install/Reload** in ELAN MagicCubeSolarPro. The expected result is three children: Solar Live, Solar Today and Solar Health. This final step has not yet been verified on a live Cube.

This is a reinstall, not an automatic migration. Existing model totals/history are not automatically transferred; retain your backup if you need them. No driver replacement, port change or file-editor access is required.

## Compatibility output

| Entity | Unit / direction |
|---|---|
| `sensor.energy_solar_power` | W |
| `sensor.energy_house_power` | W |
| `sensor.energy_grid_power` | W; positive import, negative export |
| `sensor.energy_battery_power` | W; positive charge, negative discharge |
| `sensor.energy_battery_level` | % |

Daily totals, health values and generated dashboard images follow the upstream energy model. Source states are sampled every 10 seconds; image refresh is about one minute. This is read-only and opens no extra Modbus connection. Solar Pro 26.10.26.00 requests only `innovo_energy` or `innovo_solar_edge` entries from the Cube API. This fork now uses the required `innovo_energy` domain, including services. End-to-end operation still requires confirmation on the live Cube.

## Current limits

- Firmware and enabled entities determine which lifetime counters/readings are available. Missing or unavailable live readings stay unknown, not invented zeroes.
- Daily/history totals start accumulating with this integration; historical Sigenergy data is not imported. The first day's totals can be partial. Missing lifetime counters prevent those totals accumulating.
- Single-phase, one-inverter scope only. No per-panel data or mapped aggregate DC voltage/current/grid L1/L2 electrical readings.
- Phase A voltage/current are labelled inverter output, not grid-meter readings. Voltage-health thresholds are unconfigured, displayed as such, rather than applying upstream US 120 V assumptions. Other upstream health heuristics are not full Sigenergy alarm decoding.
- Upgrading from 0.1.x requires reconfiguration and starts a new energy-model history store; previous accumulated model totals are not automatically migrated. Back up before changing versions.
- If source selection retries, enable the Sigenergy plant ESS SOC and grid active power sensors. Check **Settings → System → Logs** for `innovo_energy` errors. Send entity names, states, units and errors when reporting a problem; do not send tokens/passwords.

## Rollback

Remove the **Sigen Energy for ELAN** entry, remove its download through HACS, and restart Home Assistant. Reinstall/reconfigure Innovo Energy through HACS if desired, or restore your backup to recover all prior settings/history. Sigenergy ESS itself is unchanged.

## Validation

20 offline contract tests pass, along with Python compilation. Power/health pages rendered with synthetic data; units, direction, missing-data handling, grid status, single-phase selection, and counter resets were checked. Tests stub Home Assistant APIs; they do not prove a complete Home Assistant startup or live Cube/ELAN operation.

Run locally: `python -m unittest discover -s tests -v`.

## Attribution and licence

Based on Innovo Energy commit `53c0135264647de44c4a4f915c08250a0cde46b7`. Sigenergy mappings were checked against `v.1.2.7.5` commit `b66e3042de6396205c33f3603108579b7ef73e6a`.

Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Bundled font licences are retained. This independent experimental fork is not an official Innovo or Sigenergy product.
