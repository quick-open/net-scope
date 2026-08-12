"""Shared pytest fixtures for the netscope tests.

Everything here is deterministic and offline: a loopback TCP listener for the
port-scan tests, a guaranteed-closed loopback port, and a fake dnspython
resolver so DNS tests never touch the real network.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture
def open_port():
    """Open a listening TCP socket on 127.0.0.1 and yield its port number.

    The socket is closed on teardown, so a connect during the test always
    succeeds (the port is genuinely open and accepting).
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    yield port
    srv.close()


@pytest.fixture
def closed_port():
    """Yield a 127.0.0.1 port number that is guaranteed to be closed.

    We bind to grab a free port, then close it immediately so nothing is
    listening there for the duration of the test.
    """
    tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()
    return port


class FakeAnswer:
    """Mimics a dnspython Answer: iterable of rdata with ``.to_text()``."""

    def __init__(self, values):
        self._values = [_FakeRdata(v) for v in values]

    def __iter__(self):
        return iter(self._values)


class _FakeRdata:
    def __init__(self, value):
        self._value = value

    def to_text(self):
        return self._value


class FakeResolver:
    """A stand-in for ``dns.resolver.Resolver`` driven by a lookup table.

    ``table`` maps ``(name, rtype)`` -> list of string answers.  A miss raises
    ``KeyError`` (wrapped by dns_tools into a NetScopeError).
    """

    def __init__(self, table):
        self.table = table
        self.lifetime = None
        self.timeout = None

    def resolve(self, name, rtype):
        key = (str(name).rstrip("."), rtype)
        if key not in self.table:
            raise KeyError(f"no fake record for {key}")
        return FakeAnswer(self.table[key])


@pytest.fixture
def fake_resolver():
    return FakeResolver
