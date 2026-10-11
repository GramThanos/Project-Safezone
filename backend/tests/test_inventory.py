"""Tests for the inventory as bundles: sending a stack, and what comes back.

A holding is one *bundle* - a reward with the amount it was won in - and the
player acts on whole bundles. The properties worth pinning:

  * **A stack goes out as one delivery.** Several bundles of the same reward are
    one task, carrying each bundle by its row id; everything is checked before
    anything is dispatched, so a send goes whole or not at all.
  * **Only one stack at a time.** Bundles of different rewards, or of the same
    reward in different amounts, are refused together.
  * **A bundle is never split**, so it can never be sold in pieces.
  * **A half-finished delivery hands back only what is owed.** The bundles the
    task reports as landed are delivered; only the rest come back.
  * **One delivery, one message**, however many bundles it carried.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from test_coins import RouteCase  # noqa: E402

from src.models.character import Character  # noqa: E402
from src.models.inventory_item import InventoryItem  # noqa: E402
from src.models.notification import Notification  # noqa: E402
from src.models.reward import Reward  # noqa: E402
from src.routes import inventory  # noqa: E402


class StackCase(RouteCase):
    def setUp(self):
        super().setUp()
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.commit()
        self.dispatched = []
        online = mock.patch('src.routes.inventory.is_player_online', return_value=True)
        online.start()
        self.addCleanup(online.stop)
        # Alerts go to a worker thread; nothing here is about them.
        alerts = mock.patch('src.routes.inventory.alerting.emit')
        alerts.start()
        self.addCleanup(alerts.stop)

    def dispatch(self, method, path, json=None):
        """The game-server: accepts every task, and reports `self.task` back."""
        if method == 'POST':
            self.dispatched.append(json)
            return {'data': {'id': 70 + len(self.dispatched)}}, 201
        return {'data': self.task}, 200

    def send(self, ids, character_id=10):
        with mock.patch('src.routes.inventory.gs_request', side_effect=self.dispatch):
            return self.call('POST', '/api/inventory/send',
                             json={'ids': ids, 'character_id': character_id})

    def listing(self):
        with mock.patch('src.routes.inventory.gs_request', side_effect=self.dispatch):
            return self.call('GET', '/api/inventory').get_json()

    def status(self, item_id):
        self.session.expire_all()
        return self.session.get(InventoryItem, item_id).status

    def messages(self):
        return [n.title for n in self.session.query(Notification).order_by(Notification.id)]


class TestSendingAStack(StackCase):
    def test_a_stack_is_one_task_carrying_every_bundle(self):
        ids = [self.held(count=5) for _ in range(3)]
        res = self.send(ids)
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(len(self.dispatched), 1)
        task = self.dispatched[0]
        self.assertEqual(task['bundles'], [{'ref': i, 'count': 5} for i in ids])
        self.assertEqual(task['in_game_id'], 'Base.Axe')
        self.assertNotIn('count', task)
        for item_id in ids:
            self.assertEqual(self.status(item_id), InventoryItem.STATUS_SENDING)
            self.assertEqual(self.session.get(InventoryItem, item_id).task_id, 71)

    def test_a_usable_stack_carries_its_commands(self):
        ids = [self.held(reward_id=2) for _ in range(2)]
        self.assertEqual(self.send(ids).status_code, 200)
        self.assertEqual(self.dispatched[0]['commands'], 'heal')
        self.assertEqual(len(self.dispatched[0]['bundles']), 2)

    def test_bundles_of_different_sizes_are_different_stacks(self):
        res = self.send([self.held(count=5), self.held(count=10)])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.dispatched, [])

    def test_bundles_of_different_rewards_are_refused(self):
        res = self.send([self.held(), self.held(reward_id=2)])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.dispatched, [])

    def test_one_bad_bundle_stops_the_whole_send(self):
        good = self.held()
        lapsed = self.held(expires_at=datetime.utcnow() - timedelta(minutes=1))
        delivered = self.held(status=InventoryItem.STATUS_DELIVERED)
        self.assertEqual(self.send([good, lapsed]).status_code, 409)
        self.assertEqual(self.send([good, delivered]).status_code, 409)
        self.assertEqual(self.dispatched, [])
        self.assertEqual(self.status(good), InventoryItem.STATUS_HELD)

    def test_someone_elses_bundle_is_not_found(self):
        mine = self.held()
        theirs = InventoryItem(user_id=2, reward_id=1, count=1, status=InventoryItem.STATUS_HELD)
        self.session.add(theirs)
        self.session.commit()
        self.assertEqual(self.send([mine, theirs.id]).status_code, 404)
        self.assertEqual(self.dispatched, [])

    def test_a_send_is_capped_per_kind(self):
        usables = [self.held(reward_id=2) for _ in range(inventory.SEND_MAX['usable'] + 1)]
        self.assertEqual(self.send(usables).status_code, 400)
        items = [self.held() for _ in range(inventory.SEND_MAX['item'] + 1)]
        self.assertEqual(self.send(items).status_code, 400)
        self.assertEqual(self.dispatched, [])

    def test_malformed_ids_are_refused(self):
        item = self.held()
        for ids in (None, [], [item, item], ['1'], [True]):
            self.assertEqual(self.send(ids).status_code, 400, ids)

    def test_part_of_a_bundle_cannot_be_sent(self):
        item = self.held(count=10)
        with mock.patch('src.routes.inventory.gs_request', side_effect=self.dispatch):
            res = self.call('POST', f'/api/inventory/{item}/send',
                            json={'character_id': 10, 'count': 3})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.dispatched, [])

    def test_one_bundle_still_sends_on_its_own(self):
        item = self.held(count=10)
        with mock.patch('src.routes.inventory.gs_request', side_effect=self.dispatch):
            res = self.call('POST', f'/api/inventory/{item}/send', json={'character_id': 10})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['item']['id'], item)
        self.assertEqual(self.dispatched[0]['bundles'], [{'ref': item, 'count': 10}])

    def test_the_listing_tells_the_page_the_caps(self):
        self.assertEqual(self.listing()['send_max'], inventory.SEND_MAX)


class TestWhatComesBack(StackCase):
    def sent(self, n=3, count=5):
        ids = [self.held(count=count) for _ in range(n)]
        self.assertEqual(self.send(ids).status_code, 200)
        return ids

    def test_a_delivered_stack_is_one_message(self):
        ids = self.sent()
        self.task = {'status': 'completed', 'data': {'result': 'success', 'delivered_refs': ids}}
        self.listing()
        self.assertEqual({self.status(i) for i in ids}, {InventoryItem.STATUS_DELIVERED})
        self.assertEqual(self.messages(), ['3 × Axe ×5 was delivered'])

    def test_a_half_finished_delivery_hands_back_only_what_is_owed(self):
        ids = self.sent()
        self.task = {'status': 'completed',
                     'data': {'result': 'error', 'delivered_refs': ids[:2]}}
        self.listing()
        self.assertEqual([self.status(i) for i in ids],
                         [InventoryItem.STATUS_DELIVERED] * 2 + [InventoryItem.STATUS_HELD])
        self.assertEqual(self.messages(), ['2 × Axe ×5 was delivered',
                                           'Axe ×5 came back to your inventory'])

    def test_nothing_landed_brings_everything_back_once(self):
        ids = self.sent()
        self.task = {'status': 'completed', 'data': {'result': 'error', 'delivered_refs': []}}
        self.listing()
        self.assertEqual({self.status(i) for i in ids}, {InventoryItem.STATUS_HELD})
        self.assertEqual(self.messages(), ['3 × Axe ×5 came back to your inventory'])

    def test_a_task_from_before_bundles_brought_nothing(self):
        """No delivered_refs: an old single-bundle task that failed."""
        ids = self.sent(n=1)
        self.task = {'status': 'completed', 'data': {'result': 'error'}}
        self.listing()
        self.assertEqual(self.status(ids[0]), InventoryItem.STATUS_HELD)

    def test_a_queued_delivery_is_left_alone(self):
        ids = self.sent()
        self.task = {'status': 'pending', 'data': {}}
        self.listing()
        self.assertEqual({self.status(i) for i in ids}, {InventoryItem.STATUS_SENDING})
        self.assertEqual(self.messages(), [])

    def test_a_returned_bundle_can_be_sent_again(self):
        ids = self.sent(n=2)
        self.task = {'status': 'completed', 'data': {'result': 'error', 'delivered_refs': []}}
        self.listing()
        self.assertEqual(self.send(ids).status_code, 200)
        self.assertEqual(len(self.dispatched), 2)

    def test_a_usable_reads_without_an_amount(self):
        ids = [self.held(reward_id=2) for _ in range(2)]
        self.assertEqual(self.send(ids).status_code, 200)
        self.task = {'status': 'completed', 'data': {'result': 'success'}}
        self.listing()
        self.assertEqual(self.messages(), ['2 × Heal was delivered'])


if __name__ == '__main__':
    unittest.main()
