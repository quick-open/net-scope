"""DNS lookups built on ``dnspython``.

Forward/reverse resolution, a whole-zone-ish record sweep, and a tiny resolver
benchmark.  Every network call is wrapped so a lookup failure surfaces as
:class:`NetScopeError` (never a raw dnspython exception), and the resolver is
injectable so tests can pass a fake and stay offline.
"""

from __future__ import annotations

import time

from .errors import NetScopeError

# Record types offered by :func:`all_records` and the GUI dropdown.
COMMON_RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "SRV", "CAA"]


def _resolver(resolver=None):
    """Return *resolver* or a default dnspython resolver; import lazily."""
    if resolver is not None:
        return resolver
    try:
        import dns.resolver
    except ImportError as exc:  # pragma: no cover - dep is declared
        raise NetScopeError("dnspython is not installed.") from exc
    return dns.resolver.Resolver()


def resolve(name, rtype="A", resolver=None, timeout=5.0):
    """Resolve *name* for record type *rtype*; return a list of string answers.

    *resolver* lets tests inject a stub exposing ``.resolve(name, rtype)``.
    Raises :class:`NetScopeError` for NXDOMAIN, no-answer, timeouts, etc.
    """
    if not name or not str(name).strip():
        raise NetScopeError("No name to resolve.")
    name = str(name).strip()
    res = _resolver(resolver)
    try:
        res.lifetime = timeout
        res.timeout = timeout
    except Exception:
        pass
    try:
        answer = res.resolve(name, rtype)
    except Exception as exc:
        raise NetScopeError(
            f"DNS lookup of {name!r} {rtype} failed: {_reason(exc)}") from exc
    return [_render(rdata) for rdata in answer]


def reverse(ip, resolver=None, timeout=5.0):
    """Reverse-resolve *ip* to a list of PTR hostnames."""
    if not ip or not str(ip).strip():
        raise NetScopeError("No IP to reverse.")
    ip = str(ip).strip()
    try:
        import dns.reversename
    except ImportError as exc:  # pragma: no cover
        raise NetScopeError("dnspython is not installed.") from exc
    try:
        rev_name = dns.reversename.from_address(ip)
    except Exception as exc:
        raise NetScopeError(f"Not a valid IP address: {ip!r}") from exc
    return resolve(str(rev_name), "PTR", resolver=resolver, timeout=timeout)


def all_records(name, types=None, resolver=None, timeout=5.0):
    """Look up several record types for *name*; return ``{type: [answers]}``.

    Types with no records are simply omitted.  Only a total failure to query
    (e.g. dnspython missing) raises; per-type NXDOMAIN/no-answer are swallowed.
    """
    types = types or COMMON_RECORD_TYPES
    out = {}
    for rtype in types:
        if rtype == "PTR":
            continue  # PTR only makes sense for reverse()
        try:
            answers = resolve(name, rtype, resolver=resolver, timeout=timeout)
        except NetScopeError:
            answers = []
        if answers:
            out[rtype] = answers
    return out


def dns_benchmark(resolvers, name="example.com", rtype="A", timeout=3.0):
    """Time an A lookup of *name* against each resolver IP in *resolvers*.

    Returns a list of ``{"resolver": ip, "ok": bool, "ms": float|None,
    "answers": [str], "error": str|None}`` sorted fastest-first (failures last).
    """
    try:
        import dns.resolver
    except ImportError as exc:  # pragma: no cover
        raise NetScopeError("dnspython is not installed.") from exc
    if not resolvers:
        raise NetScopeError("No resolvers to benchmark.")
    rows = []
    for ip in resolvers:
        res = dns.resolver.Resolver(configure=False)
        res.nameservers = [str(ip)]
        res.lifetime = res.timeout = timeout
        start = time.perf_counter()
        try:
            answers = [_render(r) for r in res.resolve(name, rtype)]
            ms = round((time.perf_counter() - start) * 1000.0, 2)
            rows.append({"resolver": str(ip), "ok": True, "ms": ms,
                         "answers": answers, "error": None})
        except Exception as exc:
            rows.append({"resolver": str(ip), "ok": False, "ms": None,
                         "answers": [], "error": _reason(exc)})
    rows.sort(key=lambda r: (not r["ok"], r["ms"] if r["ms"] is not None else 9e9))
    return rows


def _render(rdata):
    """Render one dnspython rdata to a clean string."""
    try:
        return rdata.to_text()
    except Exception:
        return str(rdata)


def _reason(exc):
    """Short human reason for a dnspython/other exception."""
    name = type(exc).__name__
    msg = str(exc).strip()
    return f"{name}: {msg}" if msg else name
