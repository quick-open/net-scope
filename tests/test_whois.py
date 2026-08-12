"""WHOIS server selection -- pure, no sockets."""

from __future__ import annotations

import pytest

from netscope import NetScopeError, pick_whois_server
from netscope.whois_tool import IANA_WHOIS, ARIN_WHOIS


def test_com():
    assert pick_whois_server("example.com") == "whois.verisign-grs.com"


def test_org():
    assert pick_whois_server("example.org") == "whois.pir.org"


def test_net():
    assert pick_whois_server("foo.net") == "whois.verisign-grs.com"


def test_subdomain_uses_tld():
    assert pick_whois_server("www.deep.example.com") == "whois.verisign-grs.com"


def test_ipv4_goes_to_arin():
    assert pick_whois_server("8.8.8.8") == ARIN_WHOIS


def test_ipv6_goes_to_arin():
    assert pick_whois_server("2001:db8::1") == ARIN_WHOIS


def test_unknown_tld_falls_back_to_iana():
    assert pick_whois_server("example.somethingweird") == IANA_WHOIS


def test_trailing_dot_and_case():
    assert pick_whois_server("Example.COM.") == "whois.verisign-grs.com"


def test_empty_raises():
    with pytest.raises(NetScopeError):
        pick_whois_server("")
    with pytest.raises(NetScopeError):
        pick_whois_server(None)
