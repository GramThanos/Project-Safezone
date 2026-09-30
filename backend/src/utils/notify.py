"""Telling one player something about their own account.

Same posture as the audit helper: telling somebody about a thing must never
break the thing. A failure here is logged and swallowed.

The events worth recording in the audit log are largely the events worth
announcing, so these calls sit next to `audit.record` at most sites.

**This is the player-facing half only, and always addressed to one person** -
your claim was approved, your delivery failed, your ban has ended. Messages to
*staff* about the deployment are not notifications and do not come through here;
they go to the staff feed (`models/staff_alert.py`), which is one shared row
rather than a copy per moderator. Keeping the two apart is what stops an admin's
bell from mixing "your box is waiting" with "server 2 gave up starting".
"""
import logging

from src.database import db
from src.models.notification import Notification

logger = logging.getLogger(__name__)


def send(session, user_id, kind, title, body=None, link=None):
    """Queue a notification on the caller's session (caller commits)."""
    if not user_id:
        return
    try:
        session.add(Notification(
            user_id=user_id,
            kind=kind,
            title=title[:140],
            body=body,
            link=link
        ))
    except Exception as e:
        logger.error(f"Failed to queue notification ({kind}) for {user_id}: {e}")


def send_standalone(user_id, kind, title, body=None, link=None):
    """Send in its own transaction, for callers holding no session."""
    try:
        with db.get_db() as session:
            send(session, user_id, kind, title, body=body, link=link)
    except Exception as e:
        logger.error(f"Failed to send notification ({kind}) for {user_id}: {e}")
