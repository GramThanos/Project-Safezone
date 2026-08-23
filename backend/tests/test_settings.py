"""Tests for the settings registry's shape and its validators.

Reading and writing needs a database, so what is checked here is what can be
checked without one: that every declaration is usable by the panel, that the
secret ones stay secret, and that stored text coerces back to the declared type.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.utils import settings  # noqa: E402

VALID_TYPES = {'bool', 'int', 'str', 'text', 'markdown'}


class TestRegistryShape(unittest.TestCase):
    def test_every_setting_is_renderable(self):
        for key, spec in settings.REGISTRY.items():
            self.assertIn(spec['type'], VALID_TYPES, msg=key)
            self.assertTrue(spec.get('label'), msg=key)

    def test_every_setting_has_a_default_of_some_kind(self):
        # Either an environment key behind it or a literal, otherwise the panel
        # shows a blank field whose meaning nobody can work out.
        for key, spec in settings.REGISTRY.items():
            if spec.get('config') or 'default' in spec:
                continue
            # The mail settings are the deliberate exception: blank means "use
            # the game-server's own environment".
            self.assertTrue(key.startswith('smtp_'), msg=key)

    def test_secrets_are_marked_not_merely_named(self):
        for key in ('registration_password', 'smtp_password'):
            self.assertTrue(settings.REGISTRY[key].get('secret'), msg=key)

    def test_groups_are_known(self):
        for key, spec in settings.REGISTRY.items():
            self.assertIn(spec.get('group', 'operations'),
                          {'operations', 'mail', 'limits', 'site'}, msg=key)


class TestCoercion(unittest.TestCase):
    def test_bool_reads_the_stored_text(self):
        for value in ('true', 'True', '1', 'yes', 'on'):
            self.assertTrue(settings._coerce(value, 'bool'), msg=value)
        for value in ('false', '0', 'no', 'off', ''):
            self.assertFalse(settings._coerce(value, 'bool'), msg=value)

    def test_int_survives_junk(self):
        self.assertEqual(settings._coerce('24', 'int'), 24)
        self.assertIsNone(settings._coerce('later', 'int'))

    def test_absent_is_none(self):
        self.assertIsNone(settings._coerce(None, 'str'))


if __name__ == '__main__':
    unittest.main()
