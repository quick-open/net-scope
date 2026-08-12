"""TCP port scanning via non-blocking ``socket`` connects.

No raw sockets, no root, no SYN tricks -- just an ordinary ``connect`` with a
short timeout, which is deterministic and testable against a loopback listener.
:func:`check_port` probes one port; :func:`scan_ports` probes many (optionally in
parallel).  A refused connection means *closed*; a completed handshake means
*open*; a timeout means *filtered* (reported as closed with ``state`` detail).
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor

from .errors import NetScopeError

# A small, familiar preset used by the CLI's ``--common`` flag and the GUI.
COMMON_PORTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 111: "rpcbind", 135: "msrpc", 139: "netbios",
    143: "imap", 161: "snmp", 389: "ldap", 443: "https", 445: "smb",
    465: "smtps", 587: "submission", 636: "ldaps", 993: "imaps", 995: "pop3s",
    1433: "mssql", 1521: "oracle", 2049: "nfs", 3306: "mysql", 3389: "rdp",
    5432: "postgres", 5900: "vnc", 6379: "redis", 8080: "http-alt",
    8443: "https-alt", 27017: "mongodb",
}


def _resolve(host):
    """Resolve *host* to an address family + IP, raising NetScopeError."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise NetScopeError(f"Cannot resolve host {host!r}: {exc}") from exc
    if not infos:
        raise NetScopeError(f"Cannot resolve host {host!r}.")
    family, _type, _proto, _canon, sockaddr = infos[0]
    return family, sockaddr[0]


def check_port(host, port, timeout=1.0):
    """Return ``True`` if a TCP connection to *host:port* succeeds.

    A refused or unreachable port returns ``False``; a name that cannot be
    resolved raises :class:`NetScopeError`.  *timeout* is in seconds.
    """
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise NetScopeError(f"Invalid port {port!r}.") from exc
    if not 0 < port <= 65535:
        raise NetScopeError(f"Port out of range: {port}.")
    family, ip = _resolve(host)
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(max(0.05, float(timeout)))
        return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def scan_ports(host, ports=None, timeout=1.0, workers=64):
    """Scan *ports* on *host*; return a list of result dicts (sorted by port).

    Each result: ``{"port": int, "open": bool, "service": str}``.  ``ports``
    defaults to the :data:`COMMON_PORTS` preset.  The name is resolved once up
    front so an unresolvable host fails fast with :class:`NetScopeError`.
    """
    if ports is None:
        ports = sorted(COMMON_PORTS)
    port_list = _normalize_ports(ports)
    if not port_list:
        raise NetScopeError("No ports to scan.")
    _resolve(host)  # fail fast on a bad host before spawning threads

    def probe(p):
        try:
            is_open = check_port(host, p, timeout=timeout)
        except NetScopeError:
            is_open = False
        return {"port": p, "open": is_open,
                "service": COMMON_PORTS.get(p, "")}

    n = max(1, min(int(workers), len(port_list)))
    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(probe, port_list))
    results.sort(key=lambda r: r["port"])
    return results


def parse_ports(spec):
    """Parse a CLI port spec like ``"22,80,8000-8010"`` into a sorted int list.

    ``"common"`` (case-insensitive) expands to the :data:`COMMON_PORTS` preset.
    Raises :class:`NetScopeError` on malformed input.
    """
    if spec is None:
        return sorted(COMMON_PORTS)
    text = str(spec).strip()
    if not text or text.lower() == "common":
        return sorted(COMMON_PORTS)
    return _normalize_ports(text.split(","))


def _normalize_ports(ports):
    """Coerce an iterable/spec of ports (ints, ``"80"``, ``"1-3"``) to a list."""
    out = set()
    items = ports.split(",") if isinstance(ports, str) else ports
    for item in items:
        token = str(item).strip()
        if not token:
            continue
        if "-" in token:
            lo_s, _, hi_s = token.partition("-")
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError as exc:
                raise NetScopeError(f"Bad port range {token!r}.") from exc
            if lo > hi:
                lo, hi = hi, lo
            for p in range(lo, hi + 1):
                _add_port(out, p)
        else:
            try:
                _add_port(out, int(token))
            except ValueError as exc:
                raise NetScopeError(f"Bad port {token!r}.") from exc
    return sorted(out)


def _add_port(acc, p):
    if not 0 < p <= 65535:
        raise NetScopeError(f"Port out of range: {p}.")
    acc.add(p)
