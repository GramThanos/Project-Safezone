"""Tests for parsing Steam's Workshop item details.

Network is never touched: `parse_details` and `summarize` are the parts that can
be wrong in a way that matters, and both are pure. What is being pinned down is
that a "no such item" survives as a distinguishable answer — it is the check
that saves a pointless several-minute SteamCMD run, and collapsing it into a
generic failure is how that check quietly stops working.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import workshop  # noqa: E402


def response(*details):
    return {'response': {'result': 1, 'resultcount': len(details),
                         'publishedfiledetails': list(details)}}


OK_ITEM = {
    'publishedfileid': '2818490036',
    'result': 1,
    'title': "Brita's Weapon Pack",
    'description': '[h1]Guns[/h1]\nLots of [b]guns[/b] for your survivors.',
    'file_size': '524288000',
    'time_created': 1600000000,
    'time_updated': 1700000000,
    'preview_url': 'https://example.invalid/preview.jpg',
    'lifetime_subscriptions': '4200',
    'banned': 0,
    'tags': [{'tag': 'Build 41'}, {'tag': 'Weapons'}],
}


class TestSummarize(unittest.TestCase):
    def test_strips_bbcode_and_collapses_whitespace(self):
        self.assertEqual(
            workshop.summarize('[h1]Guns[/h1]\n\nLots  of [b]guns[/b].'),
            'Guns Lots of guns.')

    def test_truncates_on_a_word_boundary(self):
        text = 'word ' * 100
        summary = workshop.summarize(text, limit=20)
        self.assertTrue(summary.endswith('…'))
        self.assertLessEqual(len(summary), 21)
        self.assertNotIn('wor…', summary)

    def test_short_text_is_untouched(self):
        self.assertEqual(workshop.summarize('Small mod.'), 'Small mod.')

    def test_empty(self):
        self.assertEqual(workshop.summarize(None), '')


class TestParseDetails(unittest.TestCase):
    def test_reads_a_normal_item(self):
        entry = workshop.parse_details(response(OK_ITEM))['2818490036']
        self.assertTrue(entry['found'])
        self.assertFalse(entry['banned'])
        self.assertEqual(entry['title'], "Brita's Weapon Pack")
        self.assertEqual(entry['summary'], 'Guns Lots of guns for your survivors.')
        self.assertEqual(entry['size'], 524288000)
        self.assertEqual(entry['updated'], 1700000000)
        self.assertEqual(entry['tags'], ['Build 41', 'Weapons'])

    def test_missing_item_is_an_answer_not_an_error(self):
        entry = workshop.parse_details(
            response({'publishedfileid': '1', 'result': 9}))['1']
        self.assertFalse(entry['found'])
        self.assertIsNone(entry['title'])
        self.assertEqual(entry['result'], 9)

    def test_banned_item_is_flagged(self):
        entry = workshop.parse_details(response(
            dict(OK_ITEM, banned=1, ban_reason='Copyright')))['2818490036']
        self.assertTrue(entry['banned'])
        self.assertEqual(entry['ban_reason'], 'Copyright')

    def test_unparseable_sizes_do_not_raise(self):
        entry = workshop.parse_details(response(
            dict(OK_ITEM, file_size='', time_updated=None)))['2818490036']
        self.assertIsNone(entry['size'])
        self.assertIsNone(entry['updated'])

    def test_entries_without_an_id_are_skipped(self):
        parsed = workshop.parse_details(response({'result': 1}, OK_ITEM))
        self.assertEqual(list(parsed), ['2818490036'])

    def test_empty_and_malformed_payloads(self):
        self.assertEqual(workshop.parse_details(None), {})
        self.assertEqual(workshop.parse_details({}), {})
        self.assertEqual(workshop.parse_details({'response': {}}), {})
        self.assertEqual(workshop.parse_details(
            {'response': {'publishedfiledetails': ['nonsense']}}), {})


def collection_response(*details):
    return {'response': {'result': 1, 'resultcount': len(details),
                         'collectiondetails': list(details)}}


class TestParseCollections(unittest.TestCase):
    def test_children_keep_the_authors_order(self):
        # For a Project Zomboid collection the author's order is frequently the
        # intended load order, so discarding it would hand somebody the right
        # mods arranged the wrong way.
        parsed = workshop.parse_collections(collection_response({
            'publishedfileid': '500',
            'result': 1,
            'children': [
                {'publishedfileid': '30', 'sortorder': 2, 'filetype': 0},
                {'publishedfileid': '10', 'sortorder': 0, 'filetype': 0},
                {'publishedfileid': '20', 'sortorder': 1, 'filetype': 0},
            ],
        }))
        self.assertEqual(parsed, {'500': ['10', '20', '30']})

    def test_nested_collections_are_not_followed(self):
        # filetype 2 is another collection; following it automatically would let
        # one paste pull in hundreds of mods nobody looked at.
        parsed = workshop.parse_collections(collection_response({
            'publishedfileid': '501',
            'result': 1,
            'children': [
                {'publishedfileid': '11', 'sortorder': 0, 'filetype': 0},
                {'publishedfileid': '600', 'sortorder': 1, 'filetype': 2},
            ],
        }))
        self.assertEqual(parsed, {'501': ['11']})

    def test_a_plain_item_id_is_not_a_collection(self):
        # This is how an item id is told apart from a collection id, given that
        # both have exactly the same URL shape.
        parsed = workshop.parse_collections(collection_response(
            {'publishedfileid': '2818490036', 'result': 9}))
        self.assertEqual(parsed, {})

    def test_empty_collection(self):
        parsed = workshop.parse_collections(collection_response(
            {'publishedfileid': '502', 'result': 1, 'children': []}))
        self.assertEqual(parsed, {'502': []})

    def test_duplicates_and_bad_sortorders_survive(self):
        parsed = workshop.parse_collections(collection_response({
            'publishedfileid': '503',
            'result': 1,
            'children': [
                {'publishedfileid': '40', 'sortorder': None, 'filetype': 0},
                {'publishedfileid': '40', 'sortorder': 'x', 'filetype': 0},
                {'publishedfileid': '41', 'filetype': 0},
            ],
        }))
        self.assertEqual(parsed, {'503': ['40', '41']})

    def test_malformed_payloads(self):
        self.assertEqual(workshop.parse_collections(None), {})
        self.assertEqual(workshop.parse_collections({'response': {}}), {})
        self.assertEqual(workshop.parse_collections(
            {'response': {'collectiondetails': ['nonsense']}}), {})


class TestLookupGuards(unittest.TestCase):
    """The paths that must not reach the network."""

    def test_no_ids_is_a_no_op(self):
        self.assertEqual(workshop.lookup([]), ({}, None))

    def test_disabled_returns_nothing_without_calling_out(self):
        previous = workshop.config.WORKSHOP_METADATA
        workshop.config.WORKSHOP_METADATA = False
        try:
            self.assertEqual(workshop.lookup(['123']), ({}, None))
            self.assertEqual(workshop.collections(['123']), ({}, None))
        finally:
            workshop.config.WORKSHOP_METADATA = previous

    def test_no_collection_ids_is_a_no_op(self):
        self.assertEqual(workshop.collections([]), ({}, None))


if __name__ == '__main__':
    unittest.main()
