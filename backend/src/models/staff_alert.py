"""The staff feed: one row per alert that fired, shared by everyone who can see it.

Staff alerts used to be written as ordinary `notifications` rows, one per
moderator per event, into the same inbox that tells a *player* their reward
arrived. That conflated two unrelated things. An admin who is also a player got
"your box is waiting" and "server 2 gave up starting" in one undifferentiated
bell, could not mute either without muting the other, and had nowhere to answer
the question an operator actually asks - *did anything fire, and where did it
go?*

So a staff alert is now one row, not N. The message is identical for every
moderator, so storing it per-person was write amplification that bought nothing:
a ten-moderator deployment wrote ten rows per join. What varies per person is
only how far they have read, and that is a single timestamp on the account
(`users.staff_alerts_read_at`).

Three things follow from the shape:

  * The feed is chronological and complete, so it doubles as the "is this
    working" screen. A channel that is quiet because nothing happened now looks
    different from one that is quiet because it is broken.
  * Marking read is one write, not one per row.
  * `detail` is stored. It never leaves the deployment - the same rule the
    in-app channel always had - and it is the reason a moderator can read what a
    report said without going to look it up.

Retention matters here in a way it does not for the audit log: this is an
operational feed, not a record of who did what, and it accumulates fastest from
the highest-volume events. `prune_staff_alerts` trims it (see `utils/jobs.py`).
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from src.database import Base


class StaffAlert(Base):
    """One alert, visible to every account that may read the staff feed."""
    __tablename__ = 'staff_alerts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # The catalog key from `src/utils/alerting.py::EVENTS`. Kept so the feed can
    # be filtered by event and can show the right icon and colour; an event
    # later removed from the catalog degrades to a plain row rather than an
    # error, the same way a channel's stale subscription does.
    event = Column(String(32), nullable=False, index=True)
    title = Column(String(140), nullable=False)
    # Description, detail and fields already flattened to text by the channel
    # sender, because that rendering is what "the staff feed gets" means.
    body = Column(Text)
    link = Column(String(255))       # where in the panel this is about
    # Which server it happened on, when it happened on one. Denormalised rather
    # than joined: the manager owns the `servers` table, so this side has no
    # foreign key to point at.
    server_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # The feed is always read newest-first, and the unread count is always
    # "newer than this timestamp", so one index serves both.
    __table_args__ = (Index('ix_staff_alerts_created_at', 'created_at'),)

    def to_dict(self):
        return {
            'id': self.id,
            'event': self.event,
            'title': self.title,
            'body': self.body,
            'link': self.link,
            'server_id': self.server_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<StaffAlert(id={self.id}, event='{self.event}')>"
