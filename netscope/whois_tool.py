"""Minimal WHOIS client over a raw TCP socket to port 43.

No third-party WHOIS library: we pick the right server with the pure, testable
:func:`pick_whois_server` and then do one line-oriented socket exchange.  The
network step is guarded so any socket error becomes :class:`NetScopeError`.
"""

from __future__ import annotations

import ipaddress
import socket

from .errors import NetScopeError

WHOIS_PORT = 43
IANA_WHOIS = "whois.iana.org"

# A pragmatic TLD -> WHOIS server map for the common cases; anything unknown is
# routed to IANA, which refers on to the authoritative registry.
TLD_SERVERS = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.pir.org",
    "info": "whois.afilias.net",
    "io": "whois.nic.io",
    "ai": "whois.nic.ai",
    "co": "whois.nic.co",
    "us": "whois.nic.us",
    "uk": "whois.nic.uk",
    "dev": "whois.nic.google",
    "app": "whois.nic.google",
    "edu": "whois.educause.edu",
    "gov": "whois.dotgov.gov",
    "me": "whois.nic.me",
    "biz": "whois.nic.biz",
    "ca": "whois.cira.ca",
    "de": "whois.denic.de",
    "fr": "whois.nic.fr",
    "nl": "whois.domain-registry.nl",
    "au": "whois.auda.org.au",
    "jp": "whois.jprs.jp",
    "ru": "whois.tcinet.ru",
    "cn": "whois.cnnic.cn",
}

# Regional internet registry for IP WHOIS; ARIN refers on when needed.
ARIN_WHOIS = "whois.arin.net"


def pick_whois_server(query):
    """Choose a WHOIS server for a domain or IP. Pure; no network.

    * An IP address (v4/v6) -> ARIN (which redirects to the right RIR).
    * A domain -> the registry for its TLD, else IANA as a fallback.
    Raises :class:`NetScopeError` on empty input.
    """
    if not query or not str(query).strip():
        raise NetScopeError("No WHOIS query given.")
    q = str(query).strip().lower().rstrip(".")

    # IP address?
    try:
        ipaddress.ip_address(q)
        return ARIN_WHOIS
    except ValueError:
        pass

    if "." not in q:
        # A bare TLD or single label: ask IANA.
        return TLD_SERVERS.get(q, IANA_WHOIS)

    tld = q.rsplit(".", 1)[-1]
    return TLD_SERVERS.get(tld, IANA_WHOIS)


def _query_server(server, query, timeout=10.0):
    """One raw WHOIS exchange; returns the server's text. Guarded."""
    try:
        with socket.create_connection((server, WHOIS_PORT), timeout=timeout) as sock:
            sock.sendall((query + "\r\n").encode("utf-8", "replace"))
            chunks = []
            sock.settimeout(timeout)
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
    except OSError as exc:
        raise NetScopeError(
            f"WHOIS query to {server} failed: {exc}") from exc
    return b"".join(chunks).decode("utf-8", "replace")


def _referral_server(text):
    """Extract a 'refer:' / 'Registrar WHOIS Server:' referral, if any."""
    for line in text.splitlines():
        low = line.lower()
        for key in ("refer:", "whois server:", "registrar whois server:"):
            if low.strip().startswith(key):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    return None


def whois(query, server=None, follow=True, timeout=10.0):
    """Look up *query* (domain or IP) and return the WHOIS text.

    Picks a server with :func:`pick_whois_server` when *server* is ``None`` and,
    if *follow* is set, chases a single registry referral for a richer record.
    Any socket failure raises :class:`NetScopeError`.
    """
    if not query or not str(query).strip():
        raise NetScopeError("No WHOIS query given.")
    query = str(query).strip()
    server = server or pick_whois_server(query)
    text = _query_server(server, query, timeout=timeout)

    if follow:
        referral = _referral_server(text)
        if referral and referral.lower() != server.lower():
            try:
                more = _query_server(referral, query, timeout=timeout)
                if more.strip():
                    text = more
            except NetScopeError:
                pass  # keep the first answer if the referral is unreachable
    return text
