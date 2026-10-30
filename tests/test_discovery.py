"""Contract checks for Solar Pro discovery and provider collision handling."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'innovo_energy'

class DiscoveryTests(unittest.TestCase):
    def test_driver_domain_contract(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        constants = ast.parse((ROOT / 'const.py').read_text())
        domain = next(ast.literal_eval(n.value) for n in constants.body
                      if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DOMAIN' for t in n.targets))
        self.assertEqual(domain, 'innovo_energy')
        self.assertEqual(manifest['domain'], domain)
        self.assertEqual(ROOT.name, domain)

    def check_guard(self, platform, data=None):
        tree = ast.parse((ROOT / '__init__.py').read_text())
        setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_setup_entry')
        start = next(i for i,n in enumerate(setup.body) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'registry')
        end = next(i for i,n in enumerate(setup.body) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'source')
        entity = SimpleNamespace(platform=platform, entity_id='sensor.energy_solar_power')
        namespace = dict(hass=SimpleNamespace(data=data or {}), entry=SimpleNamespace(entry_id='current'),
                         er=SimpleNamespace(async_get=lambda h: SimpleNamespace(entities={'x':entity})),
                         DOMAIN='innovo_energy', ConfigEntryError=ValueError)
        exec(compile(ast.Module(body=setup.body[start:end], type_ignores=[]), '<setup guard>', 'exec'), namespace)

    def test_existing_own_entities_allow_reload(self):
        self.check_guard('innovo_energy')

    def test_old_providers_block_collisions(self):
        for domain in ('sigen_energy', 'innovo_solar_edge'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                self.check_guard(domain)

    def test_second_entry_blocked(self):
        with self.assertRaises(ValueError):
            self.check_guard('innovo_energy', {'innovo_energy': {'other': {}}})
