"""Tests for the game version a sleeping server advertises.

Same import dance as `test_wake_filter.py`.

While a server sleeps, this manager answers the Steam server browser in its
place. The browser will not offer a join for a server whose reported version it
does not recognise - it shows as ping -1 with no player count - so a wrong
version makes the server permanently unwakeable through Steam. That makes this
value load-bearing rather than cosmetic.

Build 42 compiles its version in rather than writing it anywhere on disk, so
the only reliable source is the server's own boot log. These tests pin the two
halves of that: recognising the version in a log line (without being fooled by
the JVM's version, which is printed right alongside it, or by a build id), and
the priority order the sleeping listener resolves it through.
"""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import pwd  # noqa: F401
except ImportError:
    sys.modules['pwd'] = types.ModuleType('pwd')

try:
    import config
    import manager_game
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    config = None
    manager_game = None
    IMPORT_ERROR = e


def _make_manager():
    """A sleeping manager with logging silenced for its whole life.

    The resolver logs when it falls through to the fallback, which is a case
    these tests exercise on purpose - so the silencing outlives construction,
    or the suite prints a warning per test.
    """
    with mock.patch.object(manager_game.GameManager, 'log',
                           lambda self, message: None):
        manager = manager_game.GameManager(
            1, 'test-server', [16261], initial_state='sleeping'
        )
    manager.log = lambda message: None
    return manager


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestScanLogForVersion(unittest.TestCase):
    """Finding the game's version in a boot log, and nothing else's."""

    def setUp(self):
        self.manager = _make_manager()

    def test_it_finds_a_plain_version_line(self):
        self.assertEqual(
            self.manager._scan_log_for_version('version=42.20.4'), '42.20.4')

    def test_it_reads_the_version_out_of_a_sentence(self):
        log = 'LOG  : General, 1718. Java Version detected\n' \
              'versionNumber=42.20.4 demo=false\n'
        self.assertEqual(self.manager._scan_log_for_version(log), '42.20.4')

    def test_a_java_version_line_is_skipped(self):
        # The JVM prints its own version during the same boot. Taking it would
        # advertise "17.0.9" as the game version and break every join.
        log = 'java.version=17.0.9\nversion=42.20.4\n'
        self.assertEqual(self.manager._scan_log_for_version(log), '42.20.4')

    def test_every_flavour_of_jvm_line_is_skipped(self):
        for line in ('java.version=17.0.9', 'JRE version 17.0.9',
                     'OpenJDK 64-Bit Server VM version 17.0.9',
                     'HotSpot version 17.0.9', 'jdk version 21.0.1'):
            with self.subTest(line=line):
                log = f'{line}\nversion=42.20.4\n'
                self.assertEqual(self.manager._scan_log_for_version(log),
                                 '42.20.4')

    def test_a_log_without_a_version_yields_nothing(self):
        # Returning None is what lets the caller try again on the next pass,
        # rather than latching onto a boot that has not printed it yet.
        log = 'LOG  : General, 1718. Loading tile definitions\n'
        self.assertIsNone(self.manager._scan_log_for_version(log))

    def test_the_first_version_line_wins(self):
        log = 'version=42.20.4\nmod version=1.2.3\n'
        self.assertEqual(self.manager._scan_log_for_version(log), '42.20.4')


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestVersionRegex(unittest.TestCase):
    """The dotted-version token used when reading a cached value back."""

    def test_a_build_id_is_not_a_version(self):
        # Steam build ids are long runs of digits and sit near version strings
        # in the same files. Matching one would advertise nonsense.
        self.assertIsNone(
            manager_game.GameManager._VERSION_RE.search('24775771'))

    def test_dotted_versions_of_each_length_match(self):
        for text in ('42.20', '42.20.4', '42.20.4.1'):
            with self.subTest(text=text):
                match = manager_game.GameManager._VERSION_RE.search(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), text)


@unittest.skipIf(manager_game is None,
                 f"game-server runtime deps not installed ({IMPORT_ERROR})")
class TestResolveGameVersion(unittest.TestCase):
    """The priority order: override, cached capture, install file, fallback.

    Each source is meant to beat the ones below it, so an operator pinning a
    version is never overruled by a stale cache, and a never-yet-booted server
    still advertises something well-formed.
    """

    def setUp(self):
        self.manager = _make_manager()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _path(self, name, contents):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(contents)
        return path

    def _patch(self, **overrides):
        defaults = {
            'GAME_VERSION': '',
            'GAME_VERSION_FILE': '',
            'GAME_VERSION_CACHE_FILE': os.path.join(self.tmp.name, 'absent'),
            'GAME_VERSION_FALLBACK': '42.0.0',
        }
        defaults.update(overrides)
        for key, value in defaults.items():
            patcher = mock.patch.object(config, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_explicit_override_wins_over_everything(self):
        self._patch(GAME_VERSION='41.78.16',
                    GAME_VERSION_CACHE_FILE=self._path('cache', '42.20.4\n'))
        self.assertEqual(self.manager._resolve_game_version(), '41.78.16')

    def test_the_captured_value_is_used_when_there_is_no_override(self):
        self._patch(GAME_VERSION_CACHE_FILE=self._path('cache', '42.20.4\n'))
        self.assertEqual(self.manager._resolve_game_version(), '42.20.4')

    def test_the_install_file_is_read_when_nothing_is_cached(self):
        self._patch(GAME_VERSION_FILE=self._path('ver', 'build 42.20.4\n'))
        self.assertEqual(self.manager._resolve_game_version(), '42.20.4')

    def test_the_cached_value_beats_the_install_file(self):
        self._patch(GAME_VERSION_CACHE_FILE=self._path('cache', '42.20.4\n'),
                    GAME_VERSION_FILE=self._path('ver', '41.78.16\n'))
        self.assertEqual(self.manager._resolve_game_version(), '42.20.4')

    def test_a_missing_file_falls_through_rather_than_raising(self):
        # A server that has never booted has no cache file. It still has to
        # advertise something, or it cannot be woken to create one.
        self._patch(GAME_VERSION_FALLBACK='42.9.9')
        self.assertEqual(self.manager._resolve_game_version(), '42.9.9')

    def test_a_cache_file_with_no_version_in_it_falls_through(self):
        self._patch(GAME_VERSION_CACHE_FILE=self._path('cache', 'garbage\n'),
                    GAME_VERSION_FALLBACK='42.9.9')
        self.assertEqual(self.manager._resolve_game_version(), '42.9.9')


if __name__ == '__main__':
    unittest.main()
