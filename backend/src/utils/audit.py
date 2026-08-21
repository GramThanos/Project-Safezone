"""Helpers for writing audit log entries."""
import logging
from src.database import db
from src.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def record(session, actor_user_id, action, target=None, detail=None):
    """Append an audit entry to the given session (caller commits).

    Auditing must never break the primary operation, so failures are swallowed
    and logged rather than raised.
    """
    try:
        session.add(AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target=target,
            detail=detail
        ))
    except Exception as e:
        logger.error(f"Failed to write audit log ({action}): {e}")


def record_standalone(actor_user_id, action, target=None, detail=None):
    """Write an audit entry in its own transaction.

    For handlers that hold no session of their own - the server and task routes
    proxy straight to the game-server and never open one. Same posture as
    ``record``: auditing must never break the operation it describes, so a
    failure here is logged and swallowed.
    """
    try:
        with db.get_db() as session:
            record(session, actor_user_id, action, target=target, detail=detail)
    except Exception as e:
        logger.error(f"Failed to write audit log ({action}): {e}")
