"""Tests for deleting the installed game files.

`steam.app_uninstall` is the one place in this service that recursively removes
a tree an operator points it at, so it gets the same treatment as the mod
library's path containment: prove it stays inside the install directory, prove
a symlink cannot lead it out, and prove the things it promises to keep are
still there afterwards.

The promises, in the order they matter:

  * Server configs and saved worlds live under ZOMBOID_DATA_DIR and are never
    reached from here at all.
  * Downloaded Workshop content lives inside the install dir but is a
    separately managed library - often tens of gigabytes - and is kept unless
    the caller explicitly asks for it to go.
  * Everything else SteamCMD laid down goes.
"""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import pwd  # noqa: F401
except ImportError:
    sys.modules['pwd'] = types.ModuleType('pwd')

# `steam` imports `vdf` for reading Steam's appmanifest, which app_uninstall
# does not touch - it is os and shutil all the way down. Stubbed like `pwd`
# above so these run on a bare checkout, per the project's stdlib-only testing
# rule; without it the whole file skips on exactly the hosts a path-containment
# test most wants to run.
try:
    import vdf  # noqa: F401
except ImportError:
    sys.modules['vdf'] = types.ModuleType('vdf')

try:
    import steam
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    steam = None
    IMPORT_ERROR = e


def _write(path, text='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path


def _can_symlink(directory):
    """Whether this host lets us make a symlink (Windows often does not)."""
    target = os.path.join(directory, '_symlink_probe_target')
    link = os.path.join(directory, '_symlink_probe_link')
    os.makedirs(target, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return False
    os.unlink(link)
    return True


@unittest.skipIf(steam is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestAppUninstall(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, 'steam-apps')
        # A plausible install: the game at the root, Steam's manifest under
        # steamapps/, and a Workshop item inside that.
        _write(os.path.join(self.root, 'ProjectZomboid64'))
        _write(os.path.join(self.root, 'steamapps', 'appmanifest_380870.acf'))
        _write(os.path.join(self.root, 'steamapps', 'workshop',
                            'content', '108600', '2392709985', 'mod.info'))
        self.workshop = os.path.join(self.root, 'steamapps', 'workshop')

    def test_it_removes_the_game_files(self):
        ok, err, _ = steam.app_uninstall(self.root)
        self.assertTrue(ok, err)
        self.assertFalse(os.path.exists(os.path.join(self.root, 'ProjectZomboid64')))

    def test_the_app_manifest_goes_with_them(self):
        # The manifest is how installed_app_state() reports a build id, so
        # leaving it behind would report a version that is no longer installed.
        steam.app_uninstall(self.root)
        self.assertFalse(os.path.exists(
            os.path.join(self.root, 'steamapps', 'appmanifest_380870.acf')))

    def test_workshop_content_is_kept_by_default(self):
        ok, err, _ = steam.app_uninstall(self.root)
        self.assertTrue(ok, err)
        self.assertTrue(os.path.exists(os.path.join(
            self.workshop, 'content', '108600', '2392709985', 'mod.info')))

    def test_workshop_content_goes_when_asked(self):
        ok, err, _ = steam.app_uninstall(self.root, keep_workshop=False)
        self.assertTrue(ok, err)
        self.assertFalse(os.path.exists(self.workshop))

    def test_steamapps_is_removed_once_it_is_empty(self):
        steam.app_uninstall(self.root, keep_workshop=False)
        self.assertFalse(os.path.exists(os.path.join(self.root, 'steamapps')))

    def test_steamapps_survives_while_it_still_holds_the_workshop(self):
        steam.app_uninstall(self.root, keep_workshop=True)
        self.assertTrue(os.path.isdir(os.path.join(self.root, 'steamapps')))

    def test_an_absent_install_dir_is_reported_not_raised(self):
        ok, err, _ = steam.app_uninstall(os.path.join(self.tmp.name, 'nope'))
        self.assertFalse(ok)
        self.assertIn('Nothing is installed', err)

    def test_an_empty_install_dir_reports_that_nothing_went(self):
        empty = os.path.join(self.tmp.name, 'empty')
        os.makedirs(empty)
        ok, err, _ = steam.app_uninstall(empty)
        self.assertFalse(ok)
        self.assertIn('Nothing was installed to remove', err)

    def test_a_symlink_out_of_the_tree_is_not_followed(self):
        # The nasty case: something inside the install dir points at data that
        # is not ours to delete. The link may go; what it points at may not.
        if not _can_symlink(self.tmp.name):
            self.skipTest('this host does not allow symlinks')
        outside = os.path.join(self.tmp.name, 'worlds')
        _write(os.path.join(outside, 'Muldraugh.bin'))
        os.symlink(outside, os.path.join(self.root, 'linked-worlds'),
                   target_is_directory=True)

        steam.app_uninstall(self.root)

        self.assertTrue(os.path.exists(os.path.join(outside, 'Muldraugh.bin')),
                        'deletion escaped the install directory')

    def test_a_workshop_symlink_is_spared_when_the_workshop_is_kept(self):
        # A Workshop library relocated to another volume and linked back in is
        # a normal layout, and "keep the mods" has to mean the real files.
        if not _can_symlink(self.tmp.name):
            self.skipTest('this host does not allow symlinks')
        relocated = os.path.join(self.tmp.name, 'workshop-volume')
        _write(os.path.join(relocated, 'content', '108600', '1', 'mod.info'))

        root = os.path.join(self.tmp.name, 'install2')
        _write(os.path.join(root, 'ProjectZomboid64'))
        os.makedirs(os.path.join(root, 'steamapps'))
        os.symlink(relocated, os.path.join(root, 'steamapps', 'workshop'),
                   target_is_directory=True)

        steam.app_uninstall(root, keep_workshop=True)

        self.assertTrue(os.path.exists(os.path.join(
            relocated, 'content', '108600', '1', 'mod.info')))


if __name__ == '__main__':
    unittest.main()
