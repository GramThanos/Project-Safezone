"""Tests for the Workshop mod library.

The security-sensitive part is `item_dir`: every path here is built from a value
that arrived over HTTP, and `remove()` deletes what it is handed. The rest cover
the mismatch reporting, which is the thing that decides whether a broken server
is diagnosable or just mysteriously unjoinable.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config  # noqa: E402
import mods  # noqa: E402


def write_mod(root, item_id, folder, *, name=None, mod_id=None, description=None,
              requires=None, nested=False):
    """Create a downloaded Workshop item containing one mod."""
    base = os.path.join(root, 'steamapps', 'workshop', 'content',
                        mods.WORKSHOP_APP_ID, str(item_id))
    if nested:
        base = os.path.join(base, 'mods')
    path = os.path.join(base, folder)
    os.makedirs(path, exist_ok=True)
    lines = []
    if name is not None:
        lines.append(f'name={name}')
    if mod_id is not None:
        lines.append(f'id={mod_id}')
    if description is not None:
        lines.append(f'description={description}')
    if requires is not None:
        lines.append(f'require={requires}')
    with open(os.path.join(path, 'mod.info'), 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    return path


class ModsTestCase(unittest.TestCase):
    """Points the module at a temporary install directory."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._install_dir = config.STEAM_INSTALL_DIR
        config.STEAM_INSTALL_DIR = self.root

    def tearDown(self):
        config.STEAM_INSTALL_DIR = self._install_dir
        # Module-level memo, and every test uses a fresh temporary directory.
        mods.forget_sizes()
        shutil.rmtree(self.root, ignore_errors=True)


class TestResolveItemId(ModsTestCase):
    def test_bare_id(self):
        self.assertEqual(mods.resolve_item_id('2818490036'), ('2818490036', None))

    def test_workshop_url(self):
        item_id, error = mods.resolve_item_id(
            'https://steamcommunity.com/sharedfiles/filedetails/?id=2822286426')
        self.assertEqual(item_id, '2822286426')
        self.assertIsNone(error)

    def test_url_with_extra_query(self):
        item_id, _ = mods.resolve_item_id(
            'https://steamcommunity.com/workshop/filedetails/?id=123&searchtext=x')
        self.assertEqual(item_id, '123')

    def test_rejects_junk(self):
        item_id, error = mods.resolve_item_id('not a mod')
        self.assertIsNone(item_id)
        self.assertIn('Could not find', error)

    def test_rejects_empty(self):
        self.assertEqual(mods.resolve_item_id('')[0], None)


class TestModInfo(ModsTestCase):
    def test_declared_id_wins_over_folder_name(self):
        write_mod(self.root, '111', 'SomeFolder', name='Brita Weapons', mod_id='BritaWeapons')
        self.assertEqual(mods.item_mods('111'),
                         [{'id': 'BritaWeapons', 'name': 'Brita Weapons',
                           'folder': 'SomeFolder', 'description': None,
                           'requires': []}])

    def test_folder_name_used_when_nothing_declared(self):
        write_mod(self.root, '112', 'PlainMod')
        self.assertEqual(mods.item_mods('112'),
                         [{'id': 'PlainMod', 'name': 'PlainMod', 'folder': 'PlainMod',
                           'description': None, 'requires': []}])

    def test_description_is_read_from_mod_info(self):
        # Already on disk, so it costs no network call and works on a host that
        # cannot reach Steam at all.
        write_mod(self.root, '116', 'Described', mod_id='Described',
                  description='Adds a thing.')
        self.assertEqual(mods.item_mods('116')[0]['description'], 'Adds a thing.')

    def test_long_description_is_shortened(self):
        write_mod(self.root, '117', 'Wordy', mod_id='Wordy', description='word ' * 200)
        self.assertTrue(mods.item_mods('117')[0]['description'].endswith('…'))

    def test_unsafe_declared_id_falls_back_to_folder(self):
        # An id we could not write into the INI safely must not reach it.
        write_mod(self.root, '113', 'SafeFolder', mod_id='bad;injected')
        self.assertEqual([m['id'] for m in mods.item_mods('113')], ['SafeFolder'])

    def test_nested_layout_is_found(self):
        write_mod(self.root, '114', 'Nested', mod_id='Nested', nested=True)
        self.assertEqual([m['id'] for m in mods.item_mods('114')], ['Nested'])

    def test_both_names_accepted_for_matching(self):
        # A server configured with either the folder or the declared id loads
        # the mod, so warning about one of them would be a false alarm.
        write_mod(self.root, '115', 'TheFolder', mod_id='TheId')
        self.assertEqual(mods.mods_in_item('115'), ['TheFolder', 'TheId'])

    def test_unknown_item_is_empty(self):
        self.assertEqual(mods.item_mods('999'), [])
        self.assertEqual(mods.item_mods('../etc'), [])


class TestRequirements(ModsTestCase):
    def test_require_line_is_parsed(self):
        write_mod(self.root, '118', 'Dependent', mod_id='Dependent',
                  requires='BaseMod, OtherMod')
        self.assertEqual(mods.item_mods('118')[0]['requires'],
                         ['BaseMod', 'OtherMod'])

    def test_parse_requires_handles_both_separators(self):
        self.assertEqual(mods.parse_requires('A,B;C'), ['A', 'B', 'C'])
        self.assertEqual(mods.parse_requires('A, A'), ['A'])
        self.assertEqual(mods.parse_requires(''), [])
        self.assertEqual(mods.parse_requires(None), [])

    def test_requirement_loaded_after_the_mod_that_needs_it(self):
        provided = {'Dependent': {'id': 'Dependent', 'requires': ['Base']},
                    'Base': {'id': 'Base', 'requires': []}}
        problems = mods.check_requirements(['Dependent', 'Base'], provided)
        self.assertEqual(problems, [{'mod': 'Dependent', 'requires': 'Base',
                                     'problem': 'order'}])

    def test_correct_order_is_clean(self):
        provided = {'Dependent': {'id': 'Dependent', 'requires': ['Base']},
                    'Base': {'id': 'Base', 'requires': []}}
        self.assertEqual(mods.check_requirements(['Base', 'Dependent'], provided), [])

    def test_requirement_not_enabled_at_all(self):
        provided = {'Dependent': {'id': 'Dependent', 'requires': ['Base']}}
        problems = mods.check_requirements(['Dependent'], provided)
        self.assertEqual(problems, [{'mod': 'Dependent', 'requires': 'Base',
                                     'problem': 'missing'}])

    def test_mods_nothing_provides_are_left_to_the_unknown_names_report(self):
        # Saying the same thing twice in different words helps nobody.
        self.assertEqual(mods.check_requirements(['Ghost'], {}), [])

    def test_status_reports_the_problems(self):
        write_mod(self.root, '210', 'Base', mod_id='Base')
        write_mod(self.root, '211', 'Dependent', mod_id='Dependent', requires='Base')
        state = mods.status(['210', '211'], ['Dependent', 'Base'])
        self.assertEqual(state['requirement_problems'],
                         [{'mod': 'Dependent', 'requires': 'Base', 'problem': 'order'}])


class TestNewlineRejection(ModsTestCase):
    r"""`$` in Python matches before a trailing newline; `\Z` does not.

    These lists are written into a file the game parses line by line, so a name
    ending in a newline turns one entry into two.
    """

    def test_item_id_with_trailing_newline(self):
        self.assertIsNone(mods.ITEM_ID_RE.match('123' + chr(10)))
        self.assertIsNotNone(mods.validate(['123' + chr(10)], []))

    def test_mod_name_with_trailing_newline(self):
        self.assertIsNone(mods.MOD_NAME_RE.match('Brita' + chr(10)))
        self.assertIsNotNone(mods.validate([], ['Brita' + chr(10)]))

    def test_item_dir_refuses_one(self):
        self.assertIsNone(mods.item_dir('123' + chr(10)))


class TestFolderNameAliasing(ModsTestCase):
    """A server may name a mod by its declared id or by its folder.

    `mods_in_item` accepts both, so everything downstream has to as well or it
    invents problems for a configuration that works.
    """

    def test_requirement_satisfied_via_folder_name(self):
        write_mod(self.root, '220', 'BaseFolder', mod_id='Base')
        write_mod(self.root, '221', 'DepFolder', mod_id='Dep', requires='Base')
        # Configured by folder name throughout, which the game accepts.
        state = mods.status(['220', '221'], ['BaseFolder', 'DepFolder'])
        self.assertEqual(state['requirement_problems'], [])
        self.assertEqual(state['unknown_mod_names'], [])

    def test_wrong_order_still_caught_via_folder_name(self):
        write_mod(self.root, '222', 'BaseFolder', mod_id='Base')
        write_mod(self.root, '223', 'DepFolder', mod_id='Dep', requires='Base')
        state = mods.status(['222', '223'], ['DepFolder', 'BaseFolder'])
        self.assertEqual(state['requirement_problems'],
                         [{'mod': 'DepFolder', 'requires': 'Base',
                           'problem': 'order'}])

    def test_requirement_named_by_folder_is_resolved(self):
        write_mod(self.root, '224', 'BaseFolder', mod_id='Base')
        write_mod(self.root, '225', 'DepFolder', mod_id='Dep',
                  requires='BaseFolder')
        state = mods.status(['224', '225'], ['Base', 'Dep'])
        self.assertEqual(state['requirement_problems'], [])

    def test_duplicate_entry_does_not_fake_a_late_dependency(self):
        provided = {'Dep': {'id': 'Dep', 'requires': ['Base']},
                    'Base': {'id': 'Base', 'requires': []}}
        # Base loads first; listing it again later must not make it look late.
        self.assertEqual(
            mods.check_requirements(['Base', 'Dep', 'Base'], provided), [])


class TestSizeCache(ModsTestCase):
    def test_size_is_reused_and_invalidated(self):
        write_mod(self.root, '230', 'Sized', mod_id='Sized')
        first = mods.item_size('230')
        self.assertGreater(first, 0)
        # Second call is served from the memo rather than re-walking.
        self.assertEqual(mods.item_size('230'), first)

        mods.forget_sizes('230')
        self.assertEqual(mods.item_size('230'), first)

    def test_content_size_sums_the_library(self):
        write_mod(self.root, '231', 'A', mod_id='A')
        write_mod(self.root, '232', 'B', mod_id='B')
        self.assertEqual(mods.content_size(),
                         mods.item_size('231') + mods.item_size('232'))

    def test_removing_an_item_drops_its_size(self):
        write_mod(self.root, '233', 'Gone', mod_id='Gone')
        mods.item_size('233')
        mods.remove('233')
        self.assertIsNone(mods.item_size('233'))
        self.assertEqual(mods.content_size(), 0)


class TestStatus(ModsTestCase):
    def test_reports_missing_download(self):
        state = mods.status(['404'], [])
        self.assertEqual(state['missing_ids'], ['404'])

    def test_reports_mod_name_no_item_provides(self):
        write_mod(self.root, '200', 'Present', mod_id='Present')
        state = mods.status(['200'], ['Present', 'Typo'])
        self.assertEqual(state['unknown_mod_names'], ['Typo'])
        self.assertEqual(state['missing_ids'], [])


class TestLibrary(ModsTestCase):
    def test_lists_downloaded_items_with_usage(self):
        write_mod(self.root, '300', 'Alpha', name='Alpha Mod', mod_id='Alpha')
        write_mod(self.root, '301', 'Beta', mod_id='Beta')
        entries = mods.library(usage={'300': ['pz1', 'pz2']})

        self.assertEqual([e['id'] for e in entries], ['300', '301'])
        self.assertEqual(entries[0]['used_by'], ['pz1', 'pz2'])
        self.assertEqual(entries[1]['used_by'], [])
        self.assertEqual(entries[0]['mods'][0]['name'], 'Alpha Mod')
        self.assertGreater(entries[0]['size'], 0)
        # Nothing was passed in, so there is no Workshop metadata to show.
        self.assertIsNone(entries[0]['workshop'])

    def test_metadata_is_merged_when_supplied(self):
        write_mod(self.root, '302', 'Gamma', mod_id='Gamma')
        entries = mods.library(metadata={'302': {'title': 'Gamma Pack'}})
        self.assertEqual(entries[0]['workshop'], {'title': 'Gamma Pack'})

    def test_empty_when_nothing_downloaded(self):
        self.assertEqual(mods.library(), [])


class TestRemove(ModsTestCase):
    def test_removes_a_downloaded_item(self):
        write_mod(self.root, '400', 'Gone', mod_id='Gone')
        ok, error = mods.remove('400')
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(mods.installed(), [])

    def test_refuses_an_item_that_is_not_downloaded(self):
        ok, error = mods.remove('401')
        self.assertFalse(ok)
        self.assertIn('not downloaded', error)

    def test_refuses_traversal(self):
        outside = os.path.join(self.root, 'keepme')
        os.makedirs(outside)
        ok, error = mods.remove('../../../keepme')
        self.assertFalse(ok)
        self.assertIn('not a Workshop item id', error)
        self.assertTrue(os.path.isdir(outside))

    def test_item_dir_rejects_non_numeric(self):
        for bad in ('..', 'abc', '1/../..', ''):
            self.assertIsNone(mods.item_dir(bad), bad)


class TestValidate(ModsTestCase):
    def test_rejects_separator_in_a_mod_name(self):
        # Both lists are written into a file the game parses; a stray separator
        # there turns one entry into two.
        self.assertIsNotNone(mods.validate([], ['Good;Evil']))

    def test_rejects_duplicates(self):
        self.assertIsNotNone(mods.validate(['1', '1'], []))
        self.assertIsNotNone(mods.validate([], ['A', 'A']))

    def test_accepts_a_normal_pair(self):
        self.assertIsNone(mods.validate(['2818490036'], ['Brita_2']))


if __name__ == '__main__':
    unittest.main()
