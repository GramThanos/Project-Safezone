"""Tests for the all-characters snapshot the coin system reads once a day.

  * **Same choice as a single lookup.** Each account's main character is the
    one `find` would return: slot 1 if there is one, otherwise its first row;
    single-player rows never appear.
  * **A save is asked for only when it can matter**, and the read waits until
    the file has been written and gone quiet - a save that never lands is
    reported, not fatal.
"""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import characters  # noqa: E402

# `tasks` reaches `steam`, which needs `pwd` (Linux) and `vdf`; neither is
# touched here, so both are stubbed as in test_uninstall. The rest of the
# runtime (redis, sqlalchemy) skips the save tests on a host without it.
for _name in ('pwd', 'vdf'):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)
try:
    import tasks  # noqa: E402
    IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on the environment
    tasks = None
    IMPORT_ERROR = exc


class Player:
    def __init__(self, owner, name, slot=1, kills=0, hours=1.0):
        self.owner, self.name, self.slot, self.kills, self.hours = owner, name, slot, kills, hours

    def getOwner(self):
        return self.owner

    def getName(self):
        return self.name

    def getSlot(self):
        return self.slot

    def getStatus(self):
        return 'alive'

    def getZombieKills(self):
        return self.kills

    def getHoursSurvived(self):
        return self.hours


class DB:
    def __init__(self, players):
        self.players = players

    def getPlayers(self):
        return list(self.players)

    def getPlayersByOwner(self, owner):
        return [p for p in self.players if (p.owner or '').lower() == owner.lower()]


class MainCharacterTests(unittest.TestCase):
    def test_one_per_account_matching_find(self):
        db = DB([Player('thanos', 'Couch Guest', slot=2), Player('Thanos', 'Da Sheep', slot=1),
                 Player('alice', 'Only One', slot=2), Player(None, 'Local Hero')])
        mains = {p.getOwner().lower(): p.getName() for p in characters.main_characters(db)}
        self.assertEqual(mains, {'thanos': 'Da Sheep', 'alice': 'Only One'})
        for owner in ('thanos', 'alice'):
            self.assertEqual(characters.find(db, owner).getName(), mains[owner])

    def test_summaries_carry_what_coins_read(self):
        db = DB([Player('thanos', 'Da Sheep', kills=86, hours=162.0)])
        with mock.patch.object(characters, 'load', return_value=(db, 'saved')):
            out = characters.summaries('alpha')
        self.assertEqual(out['saved_at'], 'saved')
        self.assertEqual(out['characters'], [{'username': 'thanos', 'name': 'Da Sheep', 'status': 'alive',
                                              'zombie_kills': 86, 'hours_survived': 162.0}])


@unittest.skipIf(tasks is None, f"game-server runtime deps not installed ({IMPORT_ERROR})")
class SaveTests(unittest.TestCase):
    server = {'id': 1, 'name': 'alpha'}

    def run_save(self, state='running', online=('thanos',), signatures=None, sent=(True, None)):
        values = {'server:1:state': state, 'server:1:online_players': json.dumps(list(online))}
        sigs = iter(signatures or [])
        with mock.patch('cache.get_value', side_effect=values.get), \
                mock.patch.object(characters, 'db_path', return_value='/x/players.db'), \
                mock.patch.object(characters, 'signature', side_effect=lambda path: next(sigs)), \
                mock.patch.object(tasks, 'send_console', return_value=sent) as send, \
                mock.patch.object(tasks.time, 'sleep'):
            result = tasks.save_for_snapshot(self.server, timeout=0.05, poll=0, quiet=0)
        return result, send

    def test_not_running_or_empty_needs_no_save(self):
        (saved, _), send = self.run_save(state='sleeping')
        self.assertIsNone(saved)
        (saved, _), send2 = self.run_save(online=())
        self.assertIsNone(saved)
        send.assert_not_called()
        send2.assert_not_called()

    def test_waits_for_the_file_to_change_and_settle(self):
        (saved, detail), send = self.run_save(signatures=['a', 'a', 'b', 'b', 'b'])
        send.assert_called_once_with(self.server, 'save')
        self.assertTrue(saved)
        self.assertIsNone(detail)

    def test_a_save_that_never_lands_is_reported(self):
        (saved, detail), _ = self.run_save(signatures=['a'] * 100000)
        self.assertFalse(saved)
        self.assertIn('did not reach', detail)

    def test_a_save_that_cannot_be_sent_is_reported(self):
        (saved, detail), _ = self.run_save(signatures=['a'], sent=(False, 'no response'))
        self.assertFalse(saved)
        self.assertIn('no response', detail)


if __name__ == '__main__':
    unittest.main()
