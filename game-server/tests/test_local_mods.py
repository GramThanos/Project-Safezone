"""Tests for mods uploaded through the panel.

The security-sensitive part is the archive: every entry name in it was chosen by
whoever made the zip, and `upload()` writes files under those names. So most of
this is about what an archive may write, and where - and about an upload that is
refused leaving what was already there untouched.
"""
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config  # noqa: E402
import local_mods  # noqa: E402
import mods  # noqa: E402


def make_zip(entries, links=()):
    """An in-memory zip. ``entries`` maps archive path -> text content."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        for name, target in links:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    buffer.seek(0)
    return buffer


def info(mod_id=None, name=None, require=None):
    lines = []
    if mod_id:
        lines.append(f'id={mod_id}')
    if name:
        lines.append(f'name={name}')
    if require:
        lines.append(f'require={require}')
    return '\n'.join(lines) + '\n'


class LocalModsTestCase(unittest.TestCase):
    """Points the modules at temporary data and install directories."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._saved = (config.ZOMBOID_DATA_DIR, config.STEAM_INSTALL_DIR,
                       config.MOD_UPLOAD_MAX_BYTES, config.MOD_UPLOAD_MAX_EXTRACTED_BYTES)
        config.ZOMBOID_DATA_DIR = os.path.join(self.root, 'Zomboid')
        config.STEAM_INSTALL_DIR = os.path.join(self.root, 'steam')
        os.makedirs(local_mods.local_dir())

    def tearDown(self):
        (config.ZOMBOID_DATA_DIR, config.STEAM_INSTALL_DIR,
         config.MOD_UPLOAD_MAX_BYTES, config.MOD_UPLOAD_MAX_EXTRACTED_BYTES) = self._saved
        mods.forget_sizes()
        shutil.rmtree(self.root, ignore_errors=True)

    def plan(self, entries, links=()):
        with zipfile.ZipFile(make_zip(entries, links)) as archive:
            return local_mods.plan(archive)

    def upload(self, entries, replace=False, reserved=(), filename='mod.zip'):
        return local_mods.upload(make_zip(entries), filename, replace=replace,
                                 reserved=reserved)

    def local(self, *parts):
        return os.path.join(local_mods.local_dir(), *parts)


class TestPlanLayouts(LocalModsTestCase):
    def test_one_mod_folder(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod', 'My Mod'),
                                    'MyMod/media/lua/a.lua': 'x'})
        self.assertIsNone(error)
        self.assertEqual([(m['folder'], m['id'], m['name']) for m in planned],
                         [('MyMod', 'MyMod', 'My Mod')])

    def test_build_42_version_folder(self):
        planned, error = self.plan({'MyMod/42/mod.info': info('MyMod'),
                                    'MyMod/common/media/x.txt': 'x'})
        self.assertIsNone(error)
        self.assertEqual([m['folder'] for m in planned], ['MyMod'])

    def test_id_comes_from_the_newest_version_folder(self):
        planned, _ = self.plan({'MyMod/42/mod.info': info('Old'),
                                'MyMod/42.10/mod.info': info('New'),
                                'MyMod/42.9/mod.info': info('Middle')})
        self.assertEqual(planned[0]['id'], 'New')

    def test_version_folder_wins_over_the_build_41_copy(self):
        planned, _ = self.plan({'MyMod/mod.info': info('B41'),
                                'MyMod/42/mod.info': info('B42')})
        self.assertEqual(planned[0]['id'], 'B42')

    def test_workshop_layout_with_several_mods(self):
        planned, error = self.plan({
            'Contents/mods/A/mod.info': info('ModA'),
            'Contents/mods/B/42/mod.info': info('ModB'),
            'preview.png': 'x',
        })
        self.assertIsNone(error)
        self.assertEqual(sorted((m['folder'], m['id']) for m in planned),
                         [('A', 'ModA'), ('B', 'ModB')])

    def test_top_level_mod_info_is_named_by_its_id(self):
        planned, error = self.plan({'mod.info': info('Loose'), 'media/a.lua': 'x'})
        self.assertIsNone(error)
        self.assertEqual(planned[0]['folder'], 'Loose')
        self.assertEqual(planned[0]['prefix'], ())

    def test_top_level_mod_info_without_an_id_is_refused(self):
        planned, error = self.plan({'mod.info': info(name='No id')})
        self.assertIsNone(planned)
        self.assertIn('id=', error)

    def test_nested_mod_info_belongs_to_the_outer_mod(self):
        planned, _ = self.plan({'Outer/mod.info': info('Outer'),
                                'Outer/media/Inner/mod.info': info('Inner')})
        self.assertEqual([m['folder'] for m in planned], ['Outer'])

    def test_no_mod_info_is_refused(self):
        planned, error = self.plan({'readme.txt': 'hello'})
        self.assertIsNone(planned)
        self.assertIn('mod.info', error)

    def test_mod_info_name_is_case_sensitive(self):
        # The game would not find `Mod.info` on Linux, so neither do we.
        planned, error = self.plan({'MyMod/Mod.info': info('MyMod')})
        self.assertIsNone(planned)

    def test_macos_metadata_is_ignored(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    '__MACOSX/MyMod/._mod.info': 'junk',
                                    '__MACOSX/Other/mod.info': info('Other')})
        self.assertIsNone(error)
        self.assertEqual([m['folder'] for m in planned], ['MyMod'])

    def test_unusable_folder_name_is_refused(self):
        planned, error = self.plan({'Bad;Name/mod.info': info('X')})
        self.assertIsNone(planned)
        self.assertIn('folder name', error)

    def test_unusable_declared_id_falls_back_to_the_folder(self):
        planned, _ = self.plan({'MyMod/mod.info': info('bad;id')})
        self.assertEqual(planned[0]['id'], 'MyMod')


class TestPlanRefusesUnsafeArchives(LocalModsTestCase):
    def test_parent_traversal(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    'MyMod/../../escape.txt': 'x'})
        self.assertIsNone(planned)
        self.assertIn('outside', error)

    def test_backslash_traversal(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    'MyMod\\..\\..\\escape.txt': 'x'})
        self.assertIsNone(planned)

    def test_absolute_path(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    '/etc/cron.d/x': 'x'})
        self.assertIsNone(planned)

    def test_drive_letter(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    'C:/Windows/x': 'x'})
        self.assertIsNone(planned)

    def test_symlink(self):
        planned, error = self.plan({'MyMod/mod.info': info('MyMod')},
                                   links=[('MyMod/media', '/etc')])
        self.assertIsNone(planned)
        self.assertIn('link', error)

    def test_declared_size_over_the_limit(self):
        config.MOD_UPLOAD_MAX_EXTRACTED_BYTES = 100
        planned, error = self.plan({'MyMod/mod.info': info('MyMod'),
                                    'MyMod/big.bin': 'x' * 200})
        self.assertIsNone(planned)
        self.assertIn('unpacks to more than', error)

    def test_two_mods_in_one_folder_name(self):
        planned, error = self.plan({'a/MyMod/mod.info': info('One'),
                                    'b/MyMod/mod.info': info('Two')})
        self.assertIsNone(planned)
        self.assertIn('two mods', error)


class TestUpload(LocalModsTestCase):
    def test_installs_the_mod_folder_only(self):
        installed, error, conflicts = self.upload({
            'Contents/mods/MyMod/mod.info': info('MyMod', 'My Mod'),
            'Contents/mods/MyMod/media/lua/a.lua': 'print(1)',
            'workshop.txt': 'not part of the mod',
        })
        self.assertIsNone(error)
        self.assertEqual(conflicts, [])
        self.assertEqual([m['id'] for m in installed], ['MyMod'])
        with open(self.local('MyMod', 'media', 'lua', 'a.lua')) as handle:
            self.assertEqual(handle.read(), 'print(1)')
        self.assertEqual(os.listdir(local_mods.local_dir()), ['MyMod'])

    def test_top_level_mod_lands_in_a_folder_named_by_its_id(self):
        installed, error, _ = self.upload({'mod.info': info('Loose'), 'media/a.lua': 'x'})
        self.assertIsNone(error)
        self.assertTrue(os.path.isfile(self.local('Loose', 'media', 'a.lua')))

    def test_staging_is_cleaned_up(self):
        self.upload({'MyMod/mod.info': info('MyMod')})
        self.assertEqual(os.listdir(local_mods.staging_dir()), [])

    def test_existing_folder_is_a_conflict_and_is_left_alone(self):
        self.upload({'MyMod/mod.info': info('MyMod'), 'MyMod/v.txt': 'one'})
        installed, error, conflicts = self.upload({'MyMod/mod.info': info('MyMod'),
                                                   'MyMod/v.txt': 'two'})
        self.assertIsNone(installed)
        self.assertEqual(conflicts, ['MyMod'])
        with open(self.local('MyMod', 'v.txt')) as handle:
            self.assertEqual(handle.read(), 'one')

    def test_replace_swaps_the_whole_folder(self):
        self.upload({'MyMod/mod.info': info('MyMod'), 'MyMod/old.txt': 'old'})
        installed, error, _ = self.upload({'MyMod/mod.info': info('MyMod'),
                                           'MyMod/new.txt': 'new'}, replace=True)
        self.assertIsNone(error)
        self.assertTrue(os.path.isfile(self.local('MyMod', 'new.txt')))
        # A replace is the new folder, not a merge over the old one.
        self.assertFalse(os.path.exists(self.local('MyMod', 'old.txt')))

    def test_name_of_a_workshop_mod_is_refused(self):
        installed, error, _ = self.upload({'MyMod/mod.info': info('Shared')},
                                          reserved={'Shared'})
        self.assertIsNone(installed)
        self.assertIn('Workshop', error)
        self.assertEqual(os.listdir(local_mods.local_dir()), [])

    def test_id_of_another_uploaded_folder_is_refused(self):
        self.upload({'First/mod.info': info('SameId')})
        installed, error, _ = self.upload({'Second/mod.info': info('SameId')})
        self.assertIsNone(installed)
        self.assertIn('First', error)

    def test_not_a_zip_name(self):
        installed, error, _ = local_mods.upload(io.BytesIO(b'x'), 'mod.rar')
        self.assertIsNone(installed)
        self.assertIn('.zip', error)

    def test_not_a_zip_content(self):
        installed, error, _ = local_mods.upload(io.BytesIO(b'not a zip'), 'mod.zip')
        self.assertIsNone(installed)
        self.assertIn('not a valid', error)

    def test_upload_over_the_size_limit(self):
        config.MOD_UPLOAD_MAX_BYTES = 10
        installed, error, _ = self.upload({'MyMod/mod.info': info('MyMod')})
        self.assertIsNone(installed)
        self.assertIn('larger than', error)
        self.assertEqual(os.listdir(local_mods.staging_dir()), [])


class TestLibrary(LocalModsTestCase):
    def test_usage_counts_by_id_and_folder(self):
        self.upload({'Folder/mod.info': info('ModId', 'Nice name')})
        self.upload({'Other/mod.info': info('Other')})
        entries = {e['folder']: e for e in local_mods.library(
            {'Folder': ['alpha'], 'ModId': ['beta']})}
        self.assertEqual(entries['Folder']['used_by'], ['alpha', 'beta'])
        self.assertEqual(entries['Folder']['name'], 'Nice name')
        self.assertEqual(entries['Other']['used_by'], [])

    def test_folders_without_mod_info_and_hidden_ones_are_not_mods(self):
        os.makedirs(self.local('Empty'))
        os.makedirs(self.local('.hidden'))
        with open(self.local('.hidden', 'mod.info'), 'w') as handle:
            handle.write(info('Hidden'))
        self.assertEqual(local_mods.installed(), [])

    def test_status_counts_local_mods_as_available(self):
        self.upload({'MyMod/mod.info': info('MyMod', require='Missing')})
        result = mods.status([], ['MyMod'], local=local_mods.installed())
        self.assertEqual(result['unknown_mod_names'], [])
        self.assertEqual(result['requirement_problems'],
                         [{'mod': 'MyMod', 'requires': 'Missing', 'problem': 'missing'}])


class TestRemove(LocalModsTestCase):
    def test_removes_the_folder(self):
        self.upload({'MyMod/mod.info': info('MyMod')})
        ok, error = local_mods.remove('MyMod')
        self.assertTrue(ok, error)
        self.assertFalse(os.path.exists(self.local('MyMod')))

    def test_refuses_names_outside_the_mods_folder(self):
        os.makedirs(local_mods.staging_dir(), exist_ok=True)
        for name in ('..', '.mod-uploads', '../mods', '', 'a/b'):
            ok, _ = local_mods.remove(name)
            self.assertFalse(ok, name)
        self.assertTrue(os.path.isdir(config.ZOMBOID_DATA_DIR))
        self.assertTrue(os.path.isdir(local_mods.staging_dir()))

    def test_refuses_a_symlinked_folder(self):
        outside = os.path.join(self.root, 'outside')
        os.makedirs(outside)
        try:
            os.symlink(outside, self.local('Linked'))
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        ok, _ = local_mods.remove('Linked')
        self.assertFalse(ok)
        self.assertTrue(os.path.isdir(outside))


if __name__ == '__main__':
    unittest.main()
