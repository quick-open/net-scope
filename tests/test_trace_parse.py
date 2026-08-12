"""Pure parsing of ``traceroute`` / ``tracert`` transcripts."""

from __future__ import annotations

from netscope import parse_trace_output

UNIX = """\
traceroute to quickopen.ai (203.0.113.10), 30 hops max, 60 byte packets
 1  _gateway (192.0.2.1)  0.512 ms  0.480 ms  0.470 ms
 2  198.51.100.1 (198.51.100.1)  8.100 ms  8.050 ms  8.200 ms
 3  * * *
 4  core.example.net (198.51.100.7)  12.3 ms  11.9 ms  12.1 ms
"""

WINDOWS = """\
Tracing route to quickopen.ai [203.0.113.10]
over a maximum of 30 hops:

  1     1 ms     1 ms     1 ms  192.0.2.1
  2    10 ms    11 ms     9 ms  198.51.100.1
  3     *        *        *     Request timed out.
  4    12 ms    12 ms    13 ms  core.example.net [198.51.100.7]

Trace complete.
"""


def test_unix_hops():
    hops = parse_trace_output(UNIX)
    assert len(hops) == 4
    assert hops[0]["hop"] == 1
    assert "192.0.2.1" in hops[0]["ips"]
    assert "_gateway" in hops[0]["hosts"]
    assert hops[0]["rtts"] == [0.512, 0.480, 0.470]
    assert hops[0]["timeout"] is False


def test_unix_timeout_hop():
    hops = parse_trace_output(UNIX)
    assert hops[2]["timeout"] is True
    assert hops[2]["rtts"] == []


def test_windows_hops():
    hops = parse_trace_output(WINDOWS)
    # header lines are ignored; 4 numbered hops remain.
    assert [h["hop"] for h in hops] == [1, 2, 3, 4]
    assert hops[1]["rtts"] == [10.0, 11.0, 9.0]
    assert "198.51.100.1" in hops[1]["ips"]
    assert hops[2]["timeout"] is True
    assert "198.51.100.7" in hops[3]["ips"]
    assert "core.example.net" in hops[3]["hosts"]


def test_empty():
    assert parse_trace_output("") == []
