"""LAN discovery: read the ARP table and/or TCP-sweep the local /24.

Two dependency-free strategies:

* :func:`arp_table` shells out to ``arp -a`` and parses it with the pure,
  testable :func:`parse_arp`; and
* :func:`sweep` does a threaded TCP-connect probe across a network to find hosts
  that answer on any of a few common ports -- no ICMP, no root.

:func:`local_ipv4` / :func:`local_network` figure out this box's own address and
/24 so the GUI can pre-fill a sensible target.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .errors import NetScopeError
from .ports import check_port

# A MAC address in colon or dash form.
_MAC_RE = re.compile(r"([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})")
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")

# Ports a live host is likely to answer on during a sweep.
SWEEP_PORTS = (80, 443, 22, 445, 139, 3389, 53, 8080)


def parse_arp(text):
    """Parse ``arp -a`` output into a list of host dicts. Pure; no I/O.

    Handles both the Windows layout (``  192.0.2.1   00-11-22-...  dynamic``)
    and the Unix layout (``gw (192.0.2.1) at 00:11:22:... on en0``).  Each
    entry: ``{"ip": str, "mac": str|None, "host": str|None}``.  Incomplete
    rows (no IP) are skipped; a ``(incomplete)`` MAC becomes ``None``.
    """
    hosts = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        ip_m = _IP_RE.search(line)
        if not ip_m:
            continue
        ip = ip_m.group(1)
        mac_m = _MAC_RE.search(line)
        mac = None
        if mac_m:
            raw = mac_m.group(1).replace("-", ":").lower()
            parts = [p.zfill(2) for p in raw.split(":")]
            mac = ":".join(parts)
        # A leading hostname in the Unix "name (ip) at mac" form.
        host = None
        stripped = line.strip()
        if not stripped.startswith(ip) and "(" in stripped:
            candidate = stripped.split("(", 1)[0].strip()
            if candidate and candidate != "?":
                host = candidate
        hosts.append({"ip": ip, "mac": mac, "host": host})
    return hosts


def arp_table():
    """Return the parsed system ARP table (list of host dicts).

    Raises :class:`NetScopeError` if the ``arp`` command is missing or errors.
    """
    cmd = ["arp", "-a"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise NetScopeError("The system 'arp' command was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise NetScopeError("arp timed out.") from exc
    return parse_arp((proc.stdout or "") + "\n" + (proc.stderr or ""))


def local_ipv4():
    """Best-effort local IPv4 of the default route (no packets actually sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # UDP connect sets a source addr only
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


def local_network(prefix=24):
    """The /prefix network this host sits on, as an ``ip_network`` string."""
    ip = local_ipv4()
    try:
        net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        return str(net)
    except ValueError as exc:  # pragma: no cover - ip is well-formed
        raise NetScopeError(f"Cannot derive local network: {exc}") from exc


def sweep(network=None, ports=SWEEP_PORTS, timeout=0.4, workers=128,
          max_hosts=1024):
    """TCP-connect sweep of *network*; return live hosts (list of dicts).

    A host is "up" if it accepts a connection on any probe port.  Defaults to
    the local /24.  Each result: ``{"ip": str, "open_ports": [int]}`` sorted by
    address.  Refuses absurdly large ranges (``max_hosts``) so a stray /8 does
    not hang the UI.
    """
    net_str = network or local_network()
    try:
        net = ipaddress.ip_network(net_str, strict=False)
    except ValueError as exc:
        raise NetScopeError(f"Invalid network {net_str!r}: {exc}") from exc
    if net.version != 4:
        raise NetScopeError("Sweep supports IPv4 networks only.")
    targets = list(net.hosts()) if net.prefixlen < 32 else [net.network_address]
    if len(targets) > max_hosts:
        raise NetScopeError(
            f"Network too large to sweep ({len(targets)} hosts > {max_hosts}). "
            f"Use a smaller prefix.")

    def probe(addr):
        ip = str(addr)
        found = []
        for p in ports:
            try:
                if check_port(ip, p, timeout=timeout):
                    found.append(p)
            except NetScopeError:
                pass
        return {"ip": ip, "open_ports": found} if found else None

    n = max(1, min(int(workers), len(targets)))
    live = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        for row in pool.map(probe, targets):
            if row:
                live.append(row)
    live.sort(key=lambda r: ipaddress.ip_address(r["ip"]))
    return live
