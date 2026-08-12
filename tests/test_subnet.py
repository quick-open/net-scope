"""Subnet calculator correctness -- pure ipaddress math, no network."""

from __future__ import annotations

import pytest

from netscope import NetScopeError, subnet_info, subnets, contains
from netscope.subnet import parse_network


def test_ipv4_24():
    info = subnet_info("192.0.2.0/24")
    assert info["version"] == 4
    assert info["network_address"] == "192.0.2.0"
    assert info["broadcast_address"] == "192.0.2.255"
    assert info["netmask"] == "255.255.255.0"
    assert info["hostmask"] == "0.0.0.255"
    assert info["num_addresses"] == 256
    assert info["num_usable_hosts"] == 254
    assert info["first_host"] == "192.0.2.1"
    assert info["last_host"] == "192.0.2.254"
    assert info["host_range"] == "192.0.2.1 - 192.0.2.254"
    assert info["is_private"] is True


def test_ipv4_host_bits_normalized():
    # strict=False must accept host bits and normalise the network.
    info = subnet_info("192.0.2.10/24")
    assert info["cidr"] == "192.0.2.0/24"
    assert info["network_address"] == "192.0.2.0"


def test_ipv4_31_point_to_point():
    info = subnet_info("198.51.100.0/31")
    assert info["num_addresses"] == 2
    assert info["num_usable_hosts"] == 2
    assert info["first_host"] == "198.51.100.0"
    assert info["last_host"] == "198.51.100.1"


def test_ipv4_32_single_host():
    info = subnet_info("198.51.100.5/32")
    assert info["num_addresses"] == 1
    assert info["num_usable_hosts"] == 1
    assert info["first_host"] == "198.51.100.5"
    assert info["last_host"] == "198.51.100.5"
    assert info["broadcast_address"] == "198.51.100.5"


def test_ipv4_8_large():
    info = subnet_info("198.51.100.0/8")
    assert info["num_addresses"] == 16777216
    assert info["num_usable_hosts"] == 16777214
    assert info["netmask"] == "255.0.0.0"


def test_ipv6_64():
    info = subnet_info("2001:db8::/64")
    assert info["version"] == 6
    assert info["broadcast_address"] is None  # IPv6 has no broadcast
    assert info["num_addresses"] == 2 ** 64
    assert info["first_host"] == "2001:db8::1"


def test_ipv6_128():
    info = subnet_info("2001:db8::1/128")
    assert info["num_addresses"] == 1
    assert info["num_usable_hosts"] == 1
    assert info["first_host"] == "2001:db8::1"


def test_public_range_flag():
    assert subnet_info("8.8.8.0/24")["is_private"] is False


def test_invalid_cidr_raises():
    with pytest.raises(NetScopeError):
        subnet_info("not-a-network")
    with pytest.raises(NetScopeError):
        subnet_info("999.1.1.0/24")
    with pytest.raises(NetScopeError):
        subnet_info("")


def test_subnets_split():
    parts = subnets("192.0.2.0/24", 26)
    assert parts == [
        "192.0.2.0/26", "192.0.2.64/26",
        "192.0.2.128/26", "192.0.2.192/26",
    ]


def test_subnets_bad_prefix_raises():
    with pytest.raises(NetScopeError):
        subnets("192.0.2.0/24", 20)  # smaller prefix than the network


def test_contains():
    assert contains("192.0.2.0/24", "192.0.2.50") is True
    assert contains("192.0.2.0/24", "198.51.100.9") is False


def test_contains_bad_address_raises():
    with pytest.raises(NetScopeError):
        contains("192.0.2.0/24", "nope")


def test_parse_network_strict():
    with pytest.raises(NetScopeError):
        parse_network("192.0.2.10/24", strict=True)
