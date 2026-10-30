# Sigen Energy for ELAN

Experimental Home Assistant integration for **Sigenergy ESS → Magic Cube → ELAN Solar Pro**. Derived from [Innovo Energy 1.2.2](https://github.com/InnovoDeveloper/innovo-energy), with a native Sigenergy source and its own HACS identity.

**Version 0.1.0 — experimental, not yet validated on a live Cube/ELAN installation.** Target: [Sigenergy ESS 1.2.7.5](https://github.com/TypQxQ/Sigenergy-Local-Modbus/tree/v.1.2.7.5), one inverter, single-phase L/N. Both integrations must run on the same Home Assistant. No ELAN Driver Studio is required.

## Install using HACS

1. Back up Home Assistant.
2. If an **Innovo Energy** integration entry is configured, back up its settings/history and remove that entry under **Settings → Devices & services** before setting up this integration. Both integrations use the common energy entity names and solar image folder. Merely disabling an entry can leave its entity names reserved. Keep Sigenergy ESS installed and running.
3. In **HACS → menu → Custom repositories**, add `https://github.com/Nyglebro/sigen-energy-elan`, category **Integration**.
4. Find **Sigen Energy for ELAN**, download it, and restart Home Assistant.
5. **Settings → Devices & services → Add integration → Sigen Energy for ELAN**. Select your Sigenergy source.
6. Enter panel count, watts, tilt/direction, battery settings and electricity tariff. Check the Home Assistant location/time zone. On the Cube, verify that the existing solar image publication folder is selected automatically.
7. Compare the five live readings below with Sigenergy. Then open the Cube's `/icons/solar/` viewer and check your existing ELAN Magic Cube Solar Pro pages.

This installs to `custom_components/sigen_energy`; it does not replace `sigen` or `innovo_energy`. Do not run the original Innovo Energy and this integration together: although their code and storage are separate, their Solar Pro output names and publication folder intentionally overlap.

## Compatibility output

| Entity | Unit / direction |
|---|---|
| `sensor.energy_solar_power` | W |
| `sensor.energy_house_power` | W |
| `sensor.energy_grid_power` | W; positive import, negative export |
| `sensor.energy_battery_power` | W; positive charge, negative discharge |
| `sensor.energy_battery_level` | % |

Daily totals, health values and generated dashboard images follow the upstream energy model. Source states are sampled every 10 seconds; image refresh is about one minute. This is read-only and opens no extra Modbus connection. The existing Solar Pro driver is expected to consume these common outputs; live compatibility remains to be tested, particularly any driver functions that depend on the original integration/service domain rather than entity names. Services in this fork use `sigen_energy`.

## Current limits

- Firmware and enabled entities determine which lifetime counters/readings are available. Missing or unavailable live readings stay unknown, not invented zeroes.
- Daily/history totals start accumulating with this integration; historical Sigenergy data is not imported. The first day's totals can be partial. Missing lifetime counters prevent those totals accumulating.
- Single-phase, one-inverter scope only. No per-panel data or mapped aggregate DC voltage/current/grid L1/L2 electrical readings.
- Phase A voltage/current are labelled inverter output, not grid-meter readings. Voltage-health thresholds are unconfigured, displayed as such, rather than applying upstream US 120 V assumptions. Other upstream health heuristics are not full Sigenergy alarm decoding.
- New domain means a new integration and history store. This is not an automatic migration from the earlier manually patched Innovo build.
- If source selection retries, enable the Sigenergy plant ESS SOC and grid active power sensors. Check **Settings → System → Logs** for `sigen_energy` errors. Send entity names, states, units and errors when reporting a problem; do not send tokens/passwords.

## Rollback

Remove the **Sigen Energy for ELAN** entry, remove its download through HACS, and restart Home Assistant. Reinstall/reconfigure Innovo Energy through HACS if desired, or restore your backup to recover all prior settings/history. Sigenergy ESS itself is unchanged.

## Validation

16 offline contract tests pass, along with Python compilation. Power/health pages rendered with synthetic data; units, direction, missing-data handling, grid status, single-phase selection, and counter resets were checked. Tests stub Home Assistant APIs; they do not prove a complete Home Assistant startup or live Cube/ELAN operation.

Run locally: `python -m unittest discover -s tests -v`.

## Attribution and licence

Based on Innovo Energy commit `53c0135264647de44c4a4f915c08250a0cde46b7`. Sigenergy mappings were checked against `v.1.2.7.5` commit `b66e3042de6396205c33f3603108579b7ef73e6a`.

Apache License 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Bundled font licences are retained. This independent experimental fork is not an official Innovo or Sigenergy product.
