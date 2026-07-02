"""
RailOS Adapter Shared Socket Helpers
======================================
Provides ``recv_exactly()`` used by the OMRS and WILD TCP stream adapters.
"""
from __future__ import annotations

import socket


def recv_exactly(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes from *sock*, raising ``EOFError`` on disconnect."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("Connection closed by remote server")
        buf.extend(chunk)
    return bytes(buf)
