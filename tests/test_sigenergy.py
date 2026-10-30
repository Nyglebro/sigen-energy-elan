"""Offline contract tests. HA APIs are stubbed; not a Home Assistant runtime test."""
import ast
import asyncio
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE / 'custom_components/sigen_energy'
if not ROOT.exists():
    ROOT = BASE / 'custom_components/sigen_energy'
for name in ('homeassistant','homeassistant.config_entries','homeassistant.const','homeassistant.core',
             'homeassistant.exceptions','homeassistant.helpers','homeassistant.helpers.entity_registry',
             'homeassistant.helpers.event'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['homeassistant.config_entries'].ConfigEntry = object
sys.modules['homeassistant.const'].STATE_UNKNOWN = 'unknown'
sys.modules['homeassistant.const'].STATE_UNAVAILABLE = 'unavailable'
sys.modules['homeassistant.core'].HomeAssistant = object
class NotReady(Exception): pass
sys.modules['homeassistant.exceptions'].ConfigEntryNotReady = NotReady
er=sys.modules['homeassistant.helpers.entity_registry']
er.async_get=lambda hass: hass.registry
er.async_entries_for_config_entry=lambda registry, entry: [e for e in registry if e.config_entry_id == entry]
sys.modules['homeassistant.helpers.event'].async_track_time_interval=lambda *args: lambda: None

def load(name, path, package=False):
    spec=importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)] if package else None)
    mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod); return mod
base=load('test_sources', ROOT/'sources/__init__.py', True)
source=load('test_sources.sigenergy', ROOT/'sources/sigenergy.py')

class Tests(unittest.TestCase):
    def setUp(self):
        self.states={}; self.registry=[]
        self.hass=types.SimpleNamespace(registry=self.registry, states=types.SimpleNamespace(get=self.states.get))
        self.obj=source.SigenergySource(self.hass, types.SimpleNamespace(data={'source_entry_id':'site'}))
        self.add('plant_ess_soc', '65', '%'); self.add('plant_grid_sensor_active_power','1.5','kW')
        self.add('inverter_output_type','L/N')
        self.obj._refresh()
    def add(self,key,value,unit=None,site='site',device='plant'):
        eid='sensor.renamed_'+site+'_'+key
        self.registry.append(types.SimpleNamespace(entity_id=eid, unique_id=f'{site}_{device}_{key}',
                            config_entry_id=site, platform='sigen', disabled_by=None))
        self.states[eid]=types.SimpleNamespace(state=value, attributes={'unit_of_measurement':unit})
        return eid
    def test_setup(self): asyncio.run(self.obj.async_setup())
    def test_import_charge_units(self):
        self.add('plant_ess_power','2.2','kW'); self.obj._refresh()
        raw=self.obj.read(); self.assertEqual(raw['grid_w'],1500); self.assertEqual(raw['battery_w'],2200)
    def test_export_discharge(self):
        self.states['sensor.renamed_site_plant_grid_sensor_active_power'].state='-2'
        self.add('plant_ess_power','-1','kW');self.obj._refresh()
        self.assertEqual(self.obj.read()['grid_w'],-2000);self.assertEqual(self.obj.read()['battery_w'],-1000)
    def test_renames_and_other_sites(self):
        self.add('plant_ess_soc','99','%',site='other');self.obj._refresh()
        self.assertEqual(self.obj.read()['soe'],65)
    def test_unavailable_not_zero(self):
        for val in ('unknown','unavailable','nan','inf','oops'):
            self.states['sensor.renamed_site_plant_grid_sensor_active_power'].state=val
            self.assertIsNone(self.obj.read()['grid_w'])
    def test_unknown_unit_rejected(self):
        self.states['sensor.renamed_site_plant_grid_sensor_active_power'].attributes['unit_of_measurement']='VA'
        self.assertIsNone(self.obj.read()['grid_w'])
    def test_energy_conversion(self):
        self.add('plant_accumulated_pv_energy','2.5','MWh');self.obj._refresh()
        self.assertEqual(self.obj.read()['solar_kwh'],2500);self.assertIsNone(self.obj.read()['ac_energy'])
    def test_grid_outage_not_meter_status(self):
        self.add('plant_grid_sensor_status','Offline');self.obj._refresh();self.assertIsNone(self.obj.read()['grid_on'])
        eid=self.add('plant_on_off_grid_status','Off Grid (Auto)');self.obj._refresh()
        self.assertFalse(self.obj.read()['grid_on']); self.states[eid].state='On Grid';self.assertTrue(self.obj.read()['grid_on'])
    def test_reject_three_phase(self):
        self.states['sensor.renamed_site_inverter_output_type'].state='L1/L2/L3/N'
        with self.assertRaises(NotReady): asyncio.run(self.obj.async_setup())
    def test_duplicate_inverters(self):
        self.add('inverter_active_power','1','kW',device='one')
        self.add('inverter_active_power','2','kW',device='two')
        with self.assertRaises(NotReady): asyncio.run(self.obj.async_setup())
    def test_registry_ambiguity(self):
        self.add('plant_ess_soc','33','%',device='duplicate');self.obj._refresh()
        self.assertIsNone(self.obj.read()['soe'])
    def test_dashboard_signed_power(self):
        self.assertEqual(self.obj.dashboard_grid()['power'],'sensor.renamed_site_plant_grid_sensor_active_power')
    def test_no_fake_grid_voltage(self):
        self.add('inverter_phase_a_voltage','240','V');self.obj._refresh()
        e=self.obj.electric();self.assertEqual(e['ac_v'],240);self.assertNotIn('l1_v',e)

class ModelTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((ROOT/'energy.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EnergyModel')
        names={'_compute_live','_accumulate','_accumulate_meters'}
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
        cls.decorator_list=[];cls.bases=[]
        ns={'Any':object,'BATTERY_DEADBAND_W':100}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'energy.py','exec'),ns)
        self.m=ns['EnergyModel']();self.m.values={};self.m.settings={'battery_kwh':10};self.m.data={'acc':dict(solar=0,charged=0,discharged=0),'last':{}};self.m.has_battery=True
        self.raw=dict(direct_measurements=True,meter_counters=True,soe=65,battery_w=2000,solar_w=5000,house_w=2000,grid_w=-1000,inv_w=3000,grid_on=True,inverter_status='Running',ac_energy=None,solar_kwh=100,charged_kwh=20,discharged_kwh=10)
    def test_live_then_missing_clears(self):
        self.m._compute_live(self.raw);self.assertEqual(self.m.values['battery_state'],'Charging')
        self.raw.update(battery_w=None,solar_w=None,house_w=None)
        self.m._compute_live(self.raw)
        for k in ('battery_w','solar_w','house_w'):self.assertIsNone(self.m.values[k])
    def test_lifetime_deltas_and_reset(self):
        self.m._accumulate(self.raw)
        self.raw.update(solar_kwh=101,charged_kwh=20.5,discharged_kwh=10.25);self.m._accumulate(self.raw)
        self.assertEqual(self.m.data['acc'],dict(solar=1,charged=.5,discharged=.25))
        self.raw.update(solar_kwh=0,charged_kwh=None);self.m._accumulate(self.raw)
        self.assertEqual(self.m.data['acc']['solar'],1)
    def test_battery_counter_updates_without_solar_counter(self):
        self.m._accumulate(self.raw);self.raw.update(solar_kwh=None,charged_kwh=21)
        self.m._accumulate(self.raw);self.assertEqual(self.m.data['acc']['charged'],1)

if __name__=='__main__':unittest.main()
