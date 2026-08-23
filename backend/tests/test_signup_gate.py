"""Tests for the two gates on the signup path: the username charset, and the
invitation claim.

The claim needs a database, so this one uses SQLite in memory rather than
skipping it - the property under test is what the SQL does, and asserting on
Python objects instead would test the wrong thing entirely.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.database import Base  # noqa: E402
from src.models.invitation import Invitation  # noqa: E402
from src.routes.auth import USERNAME_RE, _claim_invitation  # noqa: E402


class TestUsernameCharset(unittest.TestCase):
    """The username is immutable and is displayed everywhere, so its contents
    are load-bearing. See the note on USERNAME_RE."""

    def accepts(self, value):
        self.assertIsNotNone(USERNAME_RE.match(value), f'should accept {value!r}')

    def rejects(self, value):
        self.assertIsNone(USERNAME_RE.match(value), f'should reject {value!r}')

    def test_accepts_ordinary_names(self):
        for name in ('abc', 'admin', 'Player_1', 'my.name', 'a-b-c', 'x' * 80):
            self.accepts(name)

    def test_enforces_length(self):
        self.rejects('ab')
        self.rejects('x' * 81)

    def test_requires_an_alphanumeric_first_character(self):
        # Otherwise a name can lead with punctuation and sort or read as
        # something it is not.
        for name in ('_leading', '.hidden', '-dash'):
            self.rejects(name)

    def test_rejects_line_breaks(self):
        # These reach an email Subject via an alert title. Python's email policy
        # refuses such a header, the error is swallowed, and the visible effect
        # is that staff alert mail quietly stops arriving.
        for name in ('evil\nBcc: x@y.com', 'evil\r\nfoo', 'trailing\n'):
            self.rejects(name)

    def test_rejects_impersonation_characters(self):
        # Homoglyphs, zero-width joiners and bidi overrides all let an account
        # render as an existing one - `admin` most of all.
        for name in ('аdmin', 'ad​min', 'ad‮min'):
            self.rejects(name)

    def test_rejects_markup_reaching_a_staff_channel(self):
        # The username is interpolated into alert titles relayed to Discord.
        for name in ('@everyone', '**bold**', '[x](http://y)', 'a b'):
            self.rejects(name)


class TestInvitationClaim(unittest.TestCase):
    """`_claim_invitation` is the authority on whether a use was available.

    The check and the increment have to be one statement. As two, concurrent
    signups could both read ``uses = 0`` and both write ``uses = 1``.
    """

    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine, tables=[Invitation.__table__])
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()

    def make(self, **kwargs):
        row = Invitation(code_hash=os.urandom(16).hex(), created_by=1,
                         max_uses=kwargs.pop('max_uses', 1),
                         uses=kwargs.pop('uses', 0), **kwargs)
        self.session.add(row)
        self.session.flush()
        return row

    def uses_of(self, row):
        self.session.expire(row)
        return row.uses

    def test_claims_an_available_use(self):
        row = self.make()
        self.assertTrue(_claim_invitation(self.session, row))
        self.assertEqual(self.uses_of(row), 1)

    def test_refuses_a_spent_invitation(self):
        row = self.make(max_uses=1, uses=1)
        self.assertFalse(_claim_invitation(self.session, row))
        self.assertEqual(self.uses_of(row), 1)

    def test_a_single_use_link_admits_exactly_one(self):
        # The bug this closes: the second claim used to succeed.
        row = self.make(max_uses=1)
        self.assertTrue(_claim_invitation(self.session, row))
        self.assertFalse(_claim_invitation(self.session, row))
        self.assertEqual(self.uses_of(row), 1)

    def test_a_multi_use_link_admits_exactly_its_quota(self):
        row = self.make(max_uses=3)
        self.assertEqual(
            [_claim_invitation(self.session, row) for _ in range(5)],
            [True, True, True, False, False]
        )
        self.assertEqual(self.uses_of(row), 3)

    def test_refuses_a_revoked_invitation(self):
        row = self.make(revoked_at=datetime.utcnow())
        self.assertFalse(_claim_invitation(self.session, row))
        self.assertEqual(self.uses_of(row), 0)

    def test_refuses_an_expired_invitation(self):
        row = self.make(expires_at=datetime.utcnow() - timedelta(minutes=1))
        self.assertFalse(_claim_invitation(self.session, row))
        self.assertEqual(self.uses_of(row), 0)

    def test_allows_one_that_has_not_expired_yet(self):
        row = self.make(expires_at=datetime.utcnow() + timedelta(days=1))
        self.assertTrue(_claim_invitation(self.session, row))

    def test_a_null_expiry_never_expires(self):
        # NULL must not fall out of the comparison and silently refuse a code
        # that was issued without a deadline.
        row = self.make(expires_at=None)
        self.assertTrue(_claim_invitation(self.session, row))

    def test_the_guard_travels_in_the_where_clause(self):
        """Atomicity comes from the predicate being evaluated by the database.

        If this ever becomes a read followed by a write, the race is back even
        though every assertion above still passes.
        """
        row = self.make(max_uses=2)
        statements = []
        from sqlalchemy import event

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(self.engine, 'before_cursor_execute', record)
        try:
            _claim_invitation(self.session, row)
        finally:
            event.remove(self.engine, 'before_cursor_execute', record)

        writes = [s for s in statements if s.strip().upper().startswith('UPDATE')]
        self.assertEqual(len(writes), 1, 'the claim must be a single statement')
        self.assertIn('WHERE', writes[0].upper())
        self.assertIn('uses', writes[0])


if __name__ == '__main__':
    unittest.main()
