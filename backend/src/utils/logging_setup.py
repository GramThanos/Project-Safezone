"""Log formatting.

Plain text by default, because a person reading `docker compose logs` is the
common case and JSON is hostile to that. Set `LOG_FORMAT=json` when something
is actually collecting the logs.
"""
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record):
        payload = {
            'time': self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        # Request context, when a handler put it there.
        for field in ('request_id', 'endpoint', 'method', 'status', 'user_id'):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(app):
    """Apply the configured format to the root logger."""
    fmt = (app.config.get('LOG_FORMAT') or 'text').lower()
    level = getattr(logging, (app.config.get('LOG_LEVEL') or 'INFO').upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if fmt == 'json':
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

    root = logging.getLogger()
    # Replace rather than add: Flask and Gunicorn both install handlers, and
    # stacking them prints every line two or three times.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    return app
