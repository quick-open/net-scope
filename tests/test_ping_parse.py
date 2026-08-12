"""Pure parsing of OS ``ping`` transcripts (Linux / macOS / Windows)."""

from __future__ import annotations

from netscope import parse_ping_output

LINUX = """\
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.8 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=13.1 ms

--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 11.800/12.400/13.100/0.531 ms
"""

MAC = """\
PING example.com (93.184.216.34): 56 data bytes
64 bytes from 93.184.216.34: icmp_seq=0 ttl=54 time=8.123 ms
64 bytes from 93.184.216.34: icmp_seq=1 ttl=54 time=9.456 ms

--- example.com ping statistics ---
2 packets transmitted, 2 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 8.123/8.789/9.456/0.667 ms
"""

WINDOWS = """\
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=14ms TTL=118
Reply from 8.8.8.8: bytes=32 time<1ms TTL=118
Reply from 8.8.8.8: bytes=32 time=15ms TTL=118
Request timed out.

Ping statistics for 8.8.8.8:
    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 15ms, Average = 9ms
"""

TOTAL_LOSS = """\
PING 198.51.100.1 (198.51.100.1) 56(84) bytes of data.

--- 198.51.100.1 ping statistics ---
4 packets transmitted, 0 received, 100% packet loss, time 3050ms
"""


def test_linux():
    r = parse_ping_output(LINUX)
    assert r["rtts"] == [12.3, 11.8, 13.1]
    assert r["transmitted"] == 3
    assert r["received"] == 3
    assert r["loss_pct"] == 0.0
    assert r["min"] == 11.8
    assert r["avg"] == 12.4
    assert r["max"] == 13.1
    assert r["mdev"] == 0.531


def test_mac():
    r = parse_ping_output(MAC)
    assert r["rtts"] == [8.123, 9.456]
    assert r["transmitted"] == 2
    assert r["received"] == 2
    assert r["avg"] == 8.789


def test_windows_sub_millisecond_and_loss():
    r = parse_ping_output(WINDOWS)
    # time<1ms counts as a real 0.0 ms reply.
    assert r["rtts"] == [14.0, 0.0, 15.0]
    assert r["transmitted"] == 4
    assert r["received"] == 3
    assert r["loss_pct"] == 25.0


def test_total_loss():
    r = parse_ping_output(TOTAL_LOSS)
    assert r["transmitted"] == 4
    assert r["received"] == 0
    assert r["loss_pct"] == 100.0
    assert r["rtts"] == []


def test_empty():
    r = parse_ping_output("")
    assert r["rtts"] == []
    assert r["received"] == 0
    assert r["loss_pct"] == 0.0
