#!/usr/bin/env python3
"""A minimal Source RCON client.

Project Zomboid speaks the Source RCON protocol, which is small enough that a
dependency would cost more than it saves: four little-endian int32s and two
null-terminated strings.

Why this exists at all: commands written to the server's stdin are *delivered*
but produce no answer, so `players` and `showoptions` were buttons that appeared
to work and returned nothing. RCON gives back what the console printed.

The stdin path is deliberately kept as the fallback. Its acknowledgement is what
makes reward delivery trustworthy, and RCON being unconfigured or down must not
stop a reward reaching a player.

    packet := int32 length | int32 id | int32 type | body\\0 | \\0

Types: 3 auth, 2 exec (and auth response), 0 response value.
"""
import logging
import socket
import struct

logger = logging.getLogger(__name__)

TYPE_AUTH = 3
TYPE_EXEC = 2
TYPE_RESPONSE = 0

# Anything longer is a malformed or hostile length prefix; refuse rather than
# trying to allocate it.
MAX_PACKET = 4096
DEFAULT_TIMEOUT = 5


class RconError(Exception):
    pass


def _encode(request_id, packet_type, body):
    payload = struct.pack('<ii', request_id, packet_type) + body.encode('utf-8') + b'\x00\x00'
    return struct.pack('<i', len(payload)) + payload


def _read_exactly(sock, count):
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RconError('connection closed by the server')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_packet(sock):
    raw_length = _read_exactly(sock, 4)
    (length,) = struct.unpack('<i', raw_length)
    if length < 10 or length > MAX_PACKET:
        raise RconError(f'implausible packet length ({length})')

    payload = _read_exactly(sock, length)
    request_id, packet_type = struct.unpack('<ii', payload[:8])
    # Body is null-terminated and followed by a second null.
    body = payload[8:].split(b'\x00', 1)[0].decode('utf-8', errors='replace')
    return request_id, packet_type, body


def execute(host, port, password, command, timeout=DEFAULT_TIMEOUT):
    """Run one command. Returns ``(output, error)`` - exactly one is None.

    A fresh connection per command: RCON sessions are cheap, and holding one
    open across a server restart is a source of confusing failures.
    """
    if not port:
        return None, 'RCON is not configured for this server'
    if not password:
        return None, 'RCON has no password set, so it is not usable'

    sock = None
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.settimeout(timeout)

        sock.sendall(_encode(1, TYPE_AUTH, password))
        request_id, packet_type, _ = _read_packet(sock)
        # Some servers send an empty RESPONSE_VALUE before the auth answer.
        if packet_type == TYPE_RESPONSE:
            request_id, packet_type, _ = _read_packet(sock)
        if request_id == -1:
            return None, 'RCON password rejected'

        sock.sendall(_encode(2, TYPE_EXEC, command))
        _, _, body = _read_packet(sock)
        return body, None
    except RconError as e:
        return None, str(e)
    except socket.timeout:
        return None, 'RCON timed out'
    except OSError as e:
        return None, f'Could not reach RCON: {e}'
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def available(server):
    """Whether a server row has enough configuration to try RCON."""
    return bool(server and server.get('rcon_port'))
