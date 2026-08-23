"""HTTP proxy helper for the game-server task/server management API.

The game-server service owns the `servers` and `tasks` tables. The backend never
touches those tables directly; instead it forwards requests to the game-server's
authenticated REST API. All helpers here return a ``(payload, status_code)`` tuple
that routes can hand straight back to Flask.
"""
import logging
import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Connection/read timeout (seconds) for calls to the game-server API.
DEFAULT_TIMEOUT = 10


def gs_request(method, path, json=None, params=None, timeout=DEFAULT_TIMEOUT):
    """Forward a request to the game-server API.

    Returns ``(payload, status_code)``. On transport failure returns a 503 with a
    generic error so callers can pass it directly to ``jsonify``.
    """
    base = current_app.config['GAME_SERVER_API_URL'].rstrip('/')
    url = f"{base}{path}"
    headers = {'Authorization': f"Bearer {current_app.config['API_TOKEN']}"}
    if json is not None:
        headers['Content-Type'] = 'application/json'

    try:
        response = requests.request(
            method, url, json=json, params=params, headers=headers, timeout=timeout
        )
    except requests.RequestException as e:
        logger.error(f"Game server request to {method} {path} failed: {e}")
        return {'error': 'Game server unavailable'}, 503

    try:
        payload = response.json()
    except ValueError:
        logger.error(f"Game server returned non-JSON response for {method} {path}")
        return {'error': 'Invalid response from game server'}, 502

    return payload, response.status_code


def gs_stream(method, path, files=None, timeout=None):
    """Forward a request and return the raw streaming ``requests.Response``.

    For endpoints whose body is not JSON: a backup download (bytes coming back)
    or an upload (a file streaming through). The caller owns the response - it
    must read/close it, typically by wrapping it in a Flask streaming response.

    Returns ``(response, None)`` on success or ``(None, (payload, status))`` on a
    transport failure, so the error can be handed straight to ``jsonify``.
    """
    base = current_app.config['GAME_SERVER_API_URL'].rstrip('/')
    url = f"{base}{path}"
    headers = {'Authorization': f"Bearer {current_app.config['API_TOKEN']}"}
    # Moving a whole world archive can take a while; the 10s default is for the
    # small JSON calls, not this.
    timeout = timeout if timeout is not None else 300

    try:
        response = requests.request(
            method, url, headers=headers, files=files, stream=True, timeout=timeout
        )
    except requests.RequestException as e:
        logger.error(f"Game server stream to {method} {path} failed: {e}")
        return None, ({'error': 'Game server unavailable'}, 503)

    return response, None
