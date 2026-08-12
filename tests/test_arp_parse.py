"""Pure parsing of ``arp -a`` output (Windows and Unix layouts)."""

from __future__ import annotations

from netscope import parse_arp

WINDOWS = """\
Interface: 192.0.2.20 --- 0xb
  Internet Address      Physical Address      Type
  192.0.2.1           00-11-22-33-44-55     dynamic
  192.0.2.5           aa-bb-cc-dd-ee-ff     dynamic
  192.0.2.255         ff-ff-ff-ff-ff-ff     static
"""

UNIX = """\
_gateway (192.0.2.1) at 00:11:22:33:44:55 [ether] on eth0
? (192.0.2.5) at aa:bb:cc:dd:ee:ff [ether] on eth0
? (192.0.2.9) at <incomplete> on eth0
"""


def test_windows():
    hosts = parse_arp(WINDOWS)
    ips = [h["ip"] for h in hosts]
    assert "192.0.2.1" in ips
    assert "192.0.2.5" in ips
    first = next(h for h in hosts if h["ip"] == "192.0.2.1")
    assert first["mac"] == "00:11:22:33:44:55"  # dashes normalised to colons
    assert first["host"] is None


def test_unix_hostname_and_mac():
    hosts = parse_arp(UNIX)
    gw = next(h for h in hosts if h["ip"] == "192.0.2.1")
    assert gw["mac"] == "00:11:22:33:44:55"
    assert gw["host"] == "_gateway"
    # a "?" hostname is treated as unknown
    known = next(h for h in hosts if h["ip"] == "192.0.2.5")
    assert known["host"] is None


def test_unix_incomplete_mac():
    hosts = parse_arp(UNIX)
    inc = next(h for h in hosts if h["ip"] == "192.0.2.9")
    assert inc["mac"] is None


def test_mac_padding():
    # single-hex-digit octets are zero-padded to two chars.
    hosts = parse_arp("? (198.51.100.1) at 0:1:2:3:4:5 [ether] on eth0")
    assert hosts[0]["mac"] == "00:01:02:03:04:05"


def test_empty():
    assert parse_arp("") == []
