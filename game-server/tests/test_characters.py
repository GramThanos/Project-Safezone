"""Tests for reading a linked character out of players.db.

Two properties are pinned here. A character is found by the account that owns
it and never by its in-game name - anyone can name their character after
somebody else's account, and a name match would hand them that account's data.
And the file is parsed once per version of the save: re-read when the game
writes it (or its WAL, or the item dictionary), not on every request.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import characters  # noqa: E402


class FakePlayer:
    def __init__(self, owner, name, slot=1):
        self.owner, self.name, self.slot = owner, name, slot

    def getSlot(self):
        return self.slot

    def toDict(self):
        return {'owner': {'username': self.owner}, 'character': {'name': self.name}}


class FakeDB:
    """The two queries `find` may use, with the library's matching rules."""

    def __init__(self, players):
        self.players = players

    def getPlayersByOwner(self, owner):
        return [p for p in self.players if (p.owner or '').lower() == owner.lower()]

    def getPlayer(self, name):  # present so a regression to it would be caught
        raise AssertionError('find must not match by character name')


class FindTests(unittest.TestCase):
    def test_matches_the_owner_case_insensitively(self):
        db = FakeDB([FakePlayer('Thanos', 'Da Sheep')])
        self.assertEqual(characters.find(db, 'thanos').name, 'Da Sheep')

    def test_a_character_named_after_an_account_does_not_match_it(self):
        # mallory's character is called "thanos"; thanos has not been saved yet.
        db = FakeDB([FakePlayer('mallory', 'thanos')])
        self.assertIsNone(characters.find(db, 'thanos'))

    def test_prefers_the_main_split_screen_slot(self):
        db = FakeDB([FakePlayer('thanos', 'Couch Guest', slot=2),
                     FakePlayer('thanos', 'Da Sheep', slot=1)])
        self.assertEqual(characters.find(db, 'thanos').name, 'Da Sheep')

    def test_single_player_rows_without_owner_never_match(self):
        db = FakeDB([FakePlayer(None, 'Local Hero')])
        self.assertIsNone(characters.find(db, ''))
        self.assertIsNone(characters.find(db, 'Local Hero'))


class LoadTests(unittest.TestCase):
    def setUp(self):
        characters._cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, 'Saves', 'Multiplayer', 'alpha')
        os.makedirs(self.folder)
        self.path = os.path.join(self.folder, 'players.db')
        patcher = mock.patch('backups.save_dir', return_value=self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.opened = []

        def fake_db(path):
            self.opened.append(path)
            return FakeDB([FakePlayer('thanos', 'Da Sheep')])

        patcher = mock.patch.object(characters, 'PlayersDB', side_effect=fake_db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, name, mtime):
        path = os.path.join(self.folder, name)
        with open(path, 'ab') as f:
            f.write(b'x')
        os.utime(path, (mtime, mtime))

    def test_missing_file_is_not_found_rather_than_a_fault(self):
        with self.assertRaises(characters.Unavailable) as ctx:
            characters.load('alpha')
        self.assertEqual(ctx.exception.status, 404)

    def test_unusable_server_name_is_refused(self):
        with mock.patch('backups.save_dir', return_value=None):
            with self.assertRaises(characters.Unavailable) as ctx:
                characters.load('../etc')
        self.assertEqual(ctx.exception.status, 400)

    def test_parsed_once_until_the_file_changes(self):
        self._write('players.db', 1_000_000)
        characters.load('alpha')
        characters.load('alpha')
        self.assertEqual(len(self.opened), 1)

        self._write('players.db', 1_000_100)
        characters.load('alpha')
        self.assertEqual(len(self.opened), 2)

    def test_a_wal_or_dictionary_change_also_rereads(self):
        self._write('players.db', 1_000_000)
        characters.load('alpha')
        self._write('players.db-wal', 1_000_050)
        characters.load('alpha')
        self._write('WorldDictionary.bin', 1_000_060)
        characters.load('alpha')
        self.assertEqual(len(self.opened), 3)

    def test_saved_at_is_the_newest_write(self):
        self._write('players.db', 1_000_000)
        self._write('players.db-wal', 1_000_050)
        _, saved_at = characters.load('alpha')
        self.assertTrue(saved_at.startswith('1970-01-12T13:47:30'))

    def test_unreadable_file_is_unavailable(self):
        self._write('players.db', 1_000_000)
        with mock.patch.object(characters, 'PlayersDB', side_effect=ValueError('locked')):
            with self.assertRaises(characters.Unavailable) as ctx:
                characters.load('alpha')
        self.assertEqual(ctx.exception.status, 503)

    def test_report_for_an_unsaved_account_is_not_found(self):
        self._write('players.db', 1_000_000)
        with self.assertRaises(characters.Unavailable) as ctx:
            characters.report('alpha', 'nobody')
        self.assertEqual(ctx.exception.status, 404)

    def test_report_returns_the_whole_character(self):
        self._write('players.db', 1_000_000)
        payload = characters.report('alpha', 'THANOS')
        self.assertEqual(payload['character']['character']['name'], 'Da Sheep')
        self.assertIn('saved_at', payload)


class LeaderboardTests(unittest.TestCase):
    """Every living, owned character - split-screen slots included, the dead
    and single-player rows left out, and one bad row not hiding the rest."""

    class Ranked:
        def __init__(self, owner, name, kills, slot=1, broken=False):
            self.owner, self.name, self.kills, self.slot, self.broken = owner, name, kills, slot, broken

        def getOwner(self):
            return self.owner

        def getName(self):
            return self.name

        def getTimeAlive(self):
            return '1 day'

        def getState(self):
            if self.broken:
                raise ValueError('undecodable')
            descriptor = mock.Mock(profession='base:fireofficer')
            return mock.Mock(descriptor=descriptor, zombie_kills=self.kills,
                             survivor_kills=0, hours_survived=24.0)

    def run_with(self, alive):
        db = mock.Mock()
        db.getAlivePlayers.return_value = alive
        with mock.patch.object(characters, 'load', return_value=(db, 'saved')):
            return characters.leaderboard('alpha')

    def test_lists_every_living_owned_character(self):
        payload = self.run_with([self.Ranked('thanos', 'Da Sheep', 5),
                                 self.Ranked('thanos', 'Couch Guest', 2, slot=2),
                                 self.Ranked(None, 'Local Hero', 99)])
        self.assertEqual([c['name'] for c in payload['characters']], ['Da Sheep', 'Couch Guest'])
        self.assertEqual(payload['saved_at'], 'saved')
        row = payload['characters'][0]
        self.assertEqual((row['zombie_kills'], row['profession'], row['hours_survived']),
                         (5, 'base:fireofficer', 24.0))

    def test_an_unreadable_character_does_not_hide_the_rest(self):
        with mock.patch.object(characters, '_log'):
            payload = self.run_with([self.Ranked('a', 'Bad', 1, broken=True),
                                     self.Ranked('b', 'Good', 2)])
        self.assertEqual([c['name'] for c in payload['characters']], ['Good'])


if __name__ == '__main__':
    unittest.main()
