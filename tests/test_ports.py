"""Port-scanning against a real loopback listener (deterministic, offline)."""

from __future__ import annotations

import pytest

from netscope import NetScopeError, check_port, scan_ports, parse_ports
from netscope.ports import COMMON_PORTS


def test_check_open(open_port):
    assert check_port("127.0.0.1", open_port, timeout=1.0) is True


def test_check_closed(closed_port):
    assert check_port("127.0.0.1", closed_port, timeout=0.5) is False


def test_check_bad_port_raises():
    with pytest.raises(NetScopeError):
        check_port("127.0.0.1", 0)
    with pytest.raises(NetScopeError):
        check_port("127.0.0.1", 99999)


def test_scan_reports_open_and_closed(open_port, closed_port):
    results = scan_ports("127.0.0.1", [open_port, closed_port], timeout=0.5)
    by_port = {r["port"]: r for r in results}
    assert by_port[open_port]["open"] is True
    assert by_port[closed_port]["open"] is False
    # results come back sorted by port number
    assert [r["port"] for r in results] == sorted([open_port, closed_port])


def test_scan_service_label(open_port):
    # a well-known port carries its service name in the preset.
    assert COMMON_PORTS[80] == "http"
    results = scan_ports("127.0.0.1", [80], timeout=0.2)
    assert results[0]["service"] == "http"


def test_parse_ports_list_and_ranges():
    assert parse_ports("22,80,8000-8002") == [22, 80, 8000, 8001, 8002]


def test_parse_ports_common():
    assert parse_ports("common") == sorted(COMMON_PORTS)
    assert parse_ports(None) == sorted(COMMON_PORTS)


def test_parse_ports_dedup_and_sort():
    assert parse_ports("80,80,22") == [22, 80]


def test_parse_ports_reversed_range():
    assert parse_ports("30-28") == [28, 29, 30]


def test_parse_ports_bad_raises():
    with pytest.raises(NetScopeError):
        parse_ports("abc")
    with pytest.raises(NetScopeError):
        parse_ports("70000")


def test_scan_empty_ports_raises():
    with pytest.raises(NetScopeError):
        scan_ports("127.0.0.1", [])
