"""Shared limit/offset paging for list endpoints.

The pagination block is added *alongside* the existing named key rather than
replacing it, so `{"users": [...]}` keeps working and callers can adopt paging
when they need it.

The game-server's task endpoints already take limit/offset; this follows the
same shape rather than inventing a second one.
"""
from flask import request

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def params(default_limit=DEFAULT_LIMIT, max_limit=MAX_LIMIT):
    """``(limit, offset)`` from the query string, clamped to something sane.

    Nonsense values fall back to the default rather than erroring: a listing is
    a read, and refusing it over a malformed query string helps nobody.
    """
    try:
        limit = int(request.args.get('limit', default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def page(query, limit, offset):
    """Apply the window, and report the unwindowed total.

    The count runs before the window so the caller can tell how much is left.
    """
    total = query.order_by(None).count()
    return query.limit(limit).offset(offset).all(), total


def meta(total, limit, offset):
    """The block to merge into a list response."""
    return {
        'total': total,
        'limit': limit,
        'offset': offset,
        'has_more': offset + limit < total,
    }
