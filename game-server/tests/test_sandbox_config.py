"""Tests for the SandboxVars.lua reader/writer.

This file is Lua that the game executes, so the parser has to be exact: it must
edit only top-level scalar keys, never a same-named key nested inside a group,
and it must preserve comments, nested tables and unrecognised lines byte for
byte. These tests pin that, plus the value typing/rendering and the template
export/import filter.

`sandbox_config` is light (no redis/sqlalchemy), so it imports directly; it only
needs `config.ZOMBOID_DATA_DIR` pointed at a temp tree.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import config
import sandbox_config


SAMPLE = """SandboxVars = {
    VERSION = 6,
    -- How many zombies { note a brace in a comment }
    Zombies = 4,
    WaterShut = 2,
    ElecShut = 2,
    FoodLootNew = 0.8,
    StatsDecrease = 3,
    WorldItemRemovalList = "Base.Hat, Base.Glasses, Base.Worm",
    ItemRemovalListBlacklistToggle = false,
    ZombieLore = {
        Speed = 2,
        Zombies = 99,
    },
    HoursForLootRespawn = 0,
}
"""


class SandboxTestBase(unittest.TestCase):
    NAME = 'test-server'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch.object(config, 'ZOMBOID_DATA_DIR', self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.makedirs(os.path.join(self.tmp, 'Server'), exist_ok=True)

    def _write(self, text=SAMPLE):
        path = os.path.join(self.tmp, 'Server', f'{self.NAME}_SandboxVars.lua')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def _read_raw(self):
        path = os.path.join(self.tmp, 'Server', f'{self.NAME}_SandboxVars.lua')
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()


class TestScanAndRead(SandboxTestBase):

    def test_it_reads_top_level_scalars_with_types(self):
        self._write()
        payload, error = sandbox_config.read(self.NAME)
        self.assertIsNone(error)
        by_key = {e['key']: e for e in payload['entries']}
        self.assertEqual(by_key['Zombies']['value'], 4)
        self.assertEqual(by_key['Zombies']['type'], 'int')
        self.assertEqual(by_key['FoodLootNew']['value'], 0.8)
        self.assertEqual(by_key['FoodLootNew']['type'], 'float')
        self.assertEqual(by_key['ItemRemovalListBlacklistToggle']['value'], False)
        self.assertEqual(by_key['ItemRemovalListBlacklistToggle']['type'], 'bool')
        self.assertEqual(by_key['WorldItemRemovalList']['value'],
                         'Base.Hat, Base.Glasses, Base.Worm')
        self.assertEqual(by_key['WorldItemRemovalList']['type'], 'string')

    def test_nested_keys_are_not_read_as_top_level(self):
        self._write()
        payload, _ = sandbox_config.read(self.NAME)
        by_key = {e['key']: e for e in payload['entries']}
        # ZombieLore.Speed is nested and must not appear at the top level.
        self.assertNotIn('Speed', by_key)
        # The top-level Zombies (4) must win over the nested Zombies (99).
        self.assertEqual(by_key['Zombies']['value'], 4)

    def test_missing_file_is_an_error(self):
        payload, error = sandbox_config.read(self.NAME)
        self.assertIsNone(payload)
        self.assertIn('No sandbox file', error)


class TestWrite(SandboxTestBase):

    def test_it_changes_only_the_value_and_keeps_the_comment(self):
        self._write()
        result, error = sandbox_config.write(self.NAME, {'WaterShut': 9})
        self.assertIsNone(error)
        self.assertEqual(result['changed'], ['WaterShut'])
        text = self._read_raw()
        self.assertIn('WaterShut = 9,', text)
        # The comment with a brace is untouched, and the nested group survives.
        self.assertIn('-- How many zombies { note a brace in a comment }', text)
        self.assertIn('        Speed = 2,', text)

    def test_it_does_not_touch_a_nested_key_of_the_same_name(self):
        self._write()
        sandbox_config.write(self.NAME, {'Zombies': 6})
        text = self._read_raw()
        self.assertIn('    Zombies = 6,', text)      # top level changed
        self.assertIn('        Zombies = 99,', text)  # nested left alone

    def test_a_string_value_is_quoted_and_escaped(self):
        self._write()
        sandbox_config.write(self.NAME, {'WorldItemRemovalList': 'Base.Hat, Base.Slug'})
        text = self._read_raw()
        self.assertIn('WorldItemRemovalList = "Base.Hat, Base.Slug",', text)

    def test_a_new_key_is_inserted_before_the_closing_brace(self):
        self._write()
        result, error = sandbox_config.write(self.NAME, {'MaxItemsForLootRespawn': 40})
        self.assertIsNone(error)
        self.assertIn('MaxItemsForLootRespawn', result['changed'])
        text = self._read_raw()
        self.assertIn('    MaxItemsForLootRespawn = 40,\n', text)
        # Still inside the table: the new line comes before the final brace.
        self.assertLess(text.index('MaxItemsForLootRespawn'), text.rindex('}'))

    def test_booleans_and_floats_render_as_lua(self):
        self._write()
        sandbox_config.write(self.NAME, {'ItemRemovalListBlacklistToggle': True,
                                         'FoodLootNew': 1.6})
        text = self._read_raw()
        self.assertIn('ItemRemovalListBlacklistToggle = true,', text)
        self.assertIn('FoodLootNew = 1.6,', text)

    def test_an_unchanged_value_is_not_reported(self):
        self._write()
        result, error = sandbox_config.write(self.NAME, {'Zombies': 4})
        self.assertIsNone(error)
        self.assertEqual(result['changed'], [])

    def test_a_stale_version_is_refused(self):
        self._write()
        result, error = sandbox_config.write(self.NAME, {'Zombies': 6},
                                             expected_version='0-0')
        self.assertIsNone(result)
        self.assertIn('Somebody else', error)

    def test_the_file_still_parses_after_a_round_trip(self):
        self._write()
        sandbox_config.write(self.NAME, {'WaterShut': 9, 'ElecShut': 9,
                                         'NewKey': 7})
        payload, error = sandbox_config.read(self.NAME)
        self.assertIsNone(error)
        by_key = {e['key']: e['value'] for e in payload['entries']}
        self.assertEqual(by_key['WaterShut'], 9)
        self.assertEqual(by_key['ElecShut'], 9)
        self.assertEqual(by_key['NewKey'], 7)


class TestTemplates(SandboxTestBase):

    def test_export_drops_version_and_carries_scalars(self):
        self._write()
        payload, error = sandbox_config.export_template(self.NAME, name='Easy mode')
        self.assertIsNone(error)
        self.assertEqual(payload['schema'], 'safezone.sandbox-template/v1')
        self.assertEqual(payload['name'], 'Easy mode')
        self.assertNotIn('VERSION', payload['sandbox'])
        self.assertEqual(payload['sandbox']['Zombies'], 4)
        self.assertEqual(payload['sandbox']['WaterShut'], 2)
        # Nested group keys are not exported.
        self.assertNotIn('Speed', payload['sandbox'])

    def test_import_applies_and_skips_the_blacklist(self):
        self._write()
        result, error = sandbox_config.import_template(self.NAME, {
            'WaterShut': 9,
            'ElecShut': 9,
            'VERSION': 999,      # must be skipped
        })
        self.assertIsNone(error)
        self.assertCountEqual(result['changed'], ['WaterShut', 'ElecShut'])
        self.assertEqual(result['skipped'], ['VERSION'])
        text = self._read_raw()
        self.assertIn('VERSION = 6,', text)   # untouched
        self.assertIn('WaterShut = 9,', text)

    def test_import_of_only_excluded_keys_is_refused(self):
        self._write()
        result, error = sandbox_config.import_template(self.NAME, {'VERSION': 1})
        self.assertIsNone(result)
        self.assertIn('excluded', error)


if __name__ == '__main__':
    unittest.main()
