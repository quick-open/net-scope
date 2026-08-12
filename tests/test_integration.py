"""Deterministic loopback probes + import/headless smoke tests."""

from __future__ import annotations

import pytest

from netscope import NetScopeError, tcp_ping, ping


def test_tcp_ping_open_port(open_port):
    res = tcp_ping("127.0.0.1", count=3, timeout=1.0, port=open_port)
    assert res["method"] == "tcp"
    assert res["transmitted"] == 3
    assert res["received"] == 3
    assert res["loss_pct"] == 0.0
    assert len(res["rtts"]) == 3
    assert res["avg"] is not None


def test_tcp_ping_closed_port_still_reachable(closed_port):
    # A refused connection means the host answered: reachable, low RTT, no loss.
    res = tcp_ping("127.0.0.1", count=2, timeout=1.0, port=closed_port)
    assert res["received"] == 2
    assert res["loss_pct"] == 0.0


def test_ping_tcp_method(open_port):
    res = ping("127.0.0.1", count=1, method="tcp", port=open_port)
    assert res["received"] == 1


def test_tcp_ping_bad_host_raises():
    with pytest.raises(NetScopeError):
        tcp_ping("no.such.host.invalid.", count=1, timeout=0.5)


def test_package_imports():
    import netscope
    for attr in ("ping", "traceroute", "scan_ports", "resolve", "whois",
                 "subnet_info", "arp_table", "NetScopeError"):
        assert hasattr(netscope, attr)


def test_gui_imports_cleanly():
    # Importing the GUI module must have no side effects (no Tk root created).
    from netscope import gui
    assert hasattr(gui, "main")
    assert callable(gui.main)


def test_gui_main_headless(monkeypatch):
    # With no display, gui.main() must degrade gracefully and return 0.
    from netscope import gui
    monkeypatch.delenv("DISPLAY", raising=False)
    rc = gui.main()
    assert rc == 0
