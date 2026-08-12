"""Subnet calculator built on the standard-library :mod:`ipaddress`.

Pure and fully deterministic -- no sockets, no I/O -- so it is trivial to unit
test.  :func:`subnet_info` turns a CIDR (IPv4 or IPv6) into a dict describing the
network, broadcast, usable host range, host count and mask.  Bad input raises
:class:`NetScopeError` with a friendly message.
"""

from __future__ import annotations

import ipaddress

from .errors import NetScopeError


def parse_network(cidr, strict=False):
    """Return an ``ip_network`` for *cidr* or raise :class:`NetScopeError`.

    ``strict=False`` (the default) tolerates host bits being set -- e.g.
    ``192.0.2.10/24`` is accepted and normalised to ``192.0.2.0/24``.
    """
    if cidr is None:
        raise NetScopeError("No network given.")
    text = str(cidr).strip()
    if not text:
        raise NetScopeError("No network given.")
    try:
        return ipaddress.ip_network(text, strict=strict)
    except ValueError as exc:
        raise NetScopeError(f"Invalid network {text!r}: {exc}") from exc


def subnet_info(cidr, strict=False):
    """Describe *cidr* as a plain dict of strings/ints.

    Keys: ``cidr``, ``version``, ``network_address``, ``broadcast_address``,
    ``netmask``, ``hostmask``, ``prefixlen``, ``num_addresses``,
    ``num_usable_hosts``, ``first_host``, ``last_host``, ``host_range``,
    ``is_private``.  ``broadcast_address`` is ``None`` for IPv6 (no broadcast).
    ``first_host``/``last_host`` are ``None`` when the block has no usable hosts
    (a /32, /128 or -- for IPv4 -- a /31 point-to-point link is reported with
    both endpoints usable).
    """
    net = parse_network(cidr, strict=strict)
    is_v4 = net.version == 4
    total = net.num_addresses

    # Usable host range.  For IPv4 a /31 (RFC 3021) and /32 have no network or
    # broadcast reservation; larger blocks reserve the first and last address.
    if is_v4 and net.prefixlen <= 30:
        first = net.network_address + 1
        last = net.broadcast_address - 1
        usable = total - 2
    elif is_v4 and net.prefixlen == 31:
        first = net.network_address
        last = net.network_address + 1
        usable = 2
    elif not is_v4 and net.prefixlen <= 126:
        first = net.network_address + 1
        last = net.broadcast_address - 1
        usable = total - 2
    else:  # /32, /128, or IPv6 /127
        first = last = net.network_address
        usable = total

    if usable <= 0:
        first = last = None
        usable = 0

    info = {
        "cidr": str(net),
        "version": net.version,
        "network_address": str(net.network_address),
        "broadcast_address": str(net.broadcast_address) if is_v4 else None,
        "netmask": str(net.netmask),
        "hostmask": str(net.hostmask),
        "prefixlen": net.prefixlen,
        "num_addresses": total,
        "num_usable_hosts": usable,
        "first_host": str(first) if first is not None else None,
        "last_host": str(last) if last is not None else None,
        "host_range": (f"{first} - {last}" if first is not None else "(none)"),
        "is_private": net.is_private,
    }
    return info


def subnets(cidr, new_prefix):
    """Split *cidr* into subnets of length *new_prefix*; return a list of CIDRs."""
    net = parse_network(cidr)
    try:
        parts = list(net.subnets(new_prefix=int(new_prefix)))
    except ValueError as exc:
        raise NetScopeError(f"Cannot split into /{new_prefix}: {exc}") from exc
    return [str(p) for p in parts]


def contains(cidr, address):
    """Return ``True`` if *address* falls inside *cidr*."""
    net = parse_network(cidr)
    try:
        addr = ipaddress.ip_address(str(address).strip())
    except ValueError as exc:
        raise NetScopeError(f"Invalid address {address!r}: {exc}") from exc
    return addr in net
