"""DNS lookups driven by an injected fake resolver -- deterministic, offline."""

from __future__ import annotations

import pytest

from netscope import NetScopeError, resolve, all_records


def test_resolve_a(fake_resolver):
    res = fake_resolver({("example.com", "A"): ["93.184.216.34"]})
    assert resolve("example.com", "A", resolver=res) == ["93.184.216.34"]


def test_resolve_multiple_answers(fake_resolver):
    res = fake_resolver({("example.com", "MX"):
                         ["10 mail1.example.com.", "20 mail2.example.com."]})
    out = resolve("example.com", "MX", resolver=res)
    assert out == ["10 mail1.example.com.", "20 mail2.example.com."]


def test_resolve_strips_trailing_dot(fake_resolver):
    # the fake table keys on the dot-stripped name; resolver is given "x."
    res = fake_resolver({("host.local", "A"): ["198.51.100.1"]})
    assert resolve("host.local.", "A", resolver=res) == ["198.51.100.1"]


def test_resolve_miss_raises(fake_resolver):
    res = fake_resolver({})
    with pytest.raises(NetScopeError):
        resolve("nope.example", "A", resolver=res)


def test_resolve_empty_name_raises(fake_resolver):
    with pytest.raises(NetScopeError):
        resolve("", "A", resolver=fake_resolver({}))


def test_all_records_omits_empty(fake_resolver):
    res = fake_resolver({
        ("example.com", "A"): ["93.184.216.34"],
        ("example.com", "NS"): ["a.iana-servers.net."],
    })
    recs = all_records("example.com", types=["A", "AAAA", "NS"], resolver=res)
    assert recs == {
        "A": ["93.184.216.34"],
        "NS": ["a.iana-servers.net."],
    }
    assert "AAAA" not in recs  # no record -> omitted, not an error


def test_resolve_localhost_real():
    # A genuinely offline lookup: 'localhost' resolves via the system without
    # any external network. Skip cleanly if the box has no hosts entry.
    try:
        answers = resolve("localhost", "A")
    except NetScopeError:
        pytest.skip("localhost has no A record on this host")
    assert any(a.startswith("127.") for a in answers)
