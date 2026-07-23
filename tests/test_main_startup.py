"""Regression tests for the Titanium startup port preflight."""
from __future__ import annotations

import socket

from main import _port_is_free


def test_port_probe_rejects_an_active_local_listener():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        assert _port_is_free(listener.getsockname()[1], "127.0.0.1") is False
    finally:
        listener.close()


def test_port_probe_accepts_a_released_local_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    assert _port_is_free(port, "127.0.0.1") is True
