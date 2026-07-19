"""Helper for writing audit log entries within an existing DB session."""
import logging
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
