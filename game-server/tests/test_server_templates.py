"""Tests for server-config template export/import in `server_config`.

The security-critical half of the feature is the blacklist: a template is authored
elsewhere and shared, so ports, credentials and per-server identity must never
travel in one - on export or import - however the template was written. These
tests pin that filter and the surrounding read/write behaviour.

`server_config` is light (no redis/sqlalchemy), so unlike the manager suites it
imports directly; it only needs `config.ZOMBOID_DATA_DIR` pointed at a temp tree.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import config
import server_config


class TemplateTestBase(unittest.TestCase):
    NAME = 'test-server'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch.object(config, 'ZOMBOID_DATA_DIR', self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.makedirs(os.path.join(self.tmp, 'Server'), exist_ok=True)

    def _write_ini(self, lines):
        path = os.path.join(self.tmp, 'Server', f'{self.NAME}.ini')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
        return path

    def _read_ini(self):
        path = os.path.join(self.tmp, 'Server', f'{self.NAME}.ini')
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()


class TestExclusionRule(unittest.TestCase):

    def test_ports_are_excluded(self):
        for key in ('DefaultPort', 'UDPPort', 'SteamPort1', 'SteamPort2', 'RCONPort'):
            self.assertTrue(server_config.is_template_excluded(key), key)

    def test_credentials_are_excluded(self):
        self.assertTrue(server_config.is_template_excluded('Password'))
        self.assertTrue(server_config.is_template_excluded('RCONPassword'))

    def test_identity_is_excluded(self):
        for key in ('PublicName', 'PublicDescription', 'ResetID', 'ServerPlayerID'):
            self.assertTrue(server_config.is_template_excluded(key), key)

    def test_a_future_port_or_password_key_is_caught_by_suffix(self):
        self.assertTrue(server_config.is_template_excluded('SomeNewPort'))
        self.assertTrue(server_config.is_template_excluded('AdminPassword'))

    def test_gameplay_keys_are_allowed(self):
        for key in ('PVP', 'MaxPlayers', 'SafetySystem', 'HoursForLootRespawn'):
            self.assertFalse(server_config.is_template_excluded(key), key)


class TestExportTemplate(TemplateTestBase):

    def test_it_carries_gameplay_and_drops_the_blacklist(self):
        self._write_ini([
            'PVP=true',
            'MaxPlayers=32',
            'Password=hunter2',
            'RCONPassword=letmein',
            'DefaultPort=16261',
            'PublicName=Bob\'s Server',
            'ResetID=572058',
        ])
        payload, error = server_config.export_template(self.NAME, name='My preset')
        self.assertIsNone(error)
        self.assertEqual(payload['schema'], 'safezone.server-template/v1')
        self.assertEqual(payload['name'], 'My preset')
        self.assertEqual(payload['settings'], {'PVP': 'true', 'MaxPlayers': '32'})

    def test_disabled_keys_are_not_exported(self):
        self._write_ini(['PVP=true', '#MaxPlayers=32'])
        payload, error = server_config.export_template(self.NAME)
        self.assertIsNone(error)
        self.assertEqual(payload['settings'], {'PVP': 'true'})

    def test_missing_config_is_an_error(self):
        payload, error = server_config.export_template(self.NAME)
        self.assertIsNone(payload)
        self.assertIn('No config', error)


class TestImportTemplate(TemplateTestBase):

    def test_it_applies_allowed_keys_and_reports_skips(self):
        self._write_ini(['PVP=false', 'CustomTuning=keepme'])
        result, error = server_config.import_template(self.NAME, {
            'PVP': 'true',
            'MaxPlayers': '16',
            'Password': 'nope',        # must be skipped
            'DefaultPort': '9999',     # must be skipped
        })
        self.assertIsNone(error)
        self.assertCountEqual(result['changed'], ['PVP', 'MaxPlayers'])
        self.assertCountEqual(result['skipped'], ['Password', 'DefaultPort'])

        text = self._read_ini()
        self.assertIn('PVP=true', text)
        self.assertIn('MaxPlayers=16', text)
        # The blacklisted values never touched the file.
        self.assertNotIn('9999', text)
        self.assertNotIn('nope', text)
        # An unrelated key already in the file is preserved.
        self.assertIn('CustomTuning=keepme', text)

    def test_a_template_of_only_excluded_keys_is_refused(self):
        self._write_ini(['PVP=false'])
        result, error = server_config.import_template(self.NAME, {
            'Password': 'x', 'DefaultPort': '1', 'PublicName': 'y',
        })
        self.assertIsNone(result)
        self.assertIn('excluded', error)
        # And nothing was written.
        self.assertIn('PVP=false', self._read_ini())

    def test_an_empty_template_is_refused(self):
        self._write_ini(['PVP=false'])
        result, error = server_config.import_template(self.NAME, {})
        self.assertIsNone(result)
        self.assertIn('no settings', error)

    def test_missing_config_is_an_error(self):
        result, error = server_config.import_template(self.NAME, {'PVP': 'true'})
        self.assertIsNone(result)
        self.assertIn('No config', error)


if __name__ == '__main__':
    unittest.main()
