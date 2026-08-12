"""Traceroute via the OS ``traceroute`` (Unix) / ``tracert`` (Windows) binary.

The route logic itself needs raw sockets or elevated privileges, so we delegate
to the system tool and keep a pure, unit-testable :func:`parse_trace_output`
that turns either program's text into a list of hop dicts.  If no binary exists
we raise :class:`NetScopeError` rather than pretend.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

from .errors import NetScopeError

# A hop line, tolerant of both `traceroute` and `tracert` layouts:
#   " 1  gateway (192.0.2.1)  0.5 ms  0.4 ms  0.4 ms"   (Unix)
#   "  2    10 ms    11 ms    9 ms  198.51.100.1"             (Windows)
#   " 5  * * *"                                            (timeout)
_HOP_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
_RTT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]{2,}:[0-9a-fA-F:]*)")
_HOST_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9._\-]*[A-Za-z0-9_])")


def parse_trace_output(text):
    """Parse ``traceroute``/``tracert`` text into a list of hop dicts. Pure.

    Each hop: ``{"hop": int, "hosts": [str], "ips": [str], "rtts": [float ms],
    "timeout": bool}``.  A hop that only shows ``*`` markers has ``timeout=True``
    and empty ``rtts``.  Header/footer lines that do not start with a hop number
    are ignored.
    """
    hops = []
    for raw in (text or "").splitlines():
        m = _HOP_RE.match(raw)
        if not m:
            continue
        hop_no = int(m.group(1))
        rest = m.group(2)
        rtts = [float(x) for x in _RTT_RE.findall(rest)]
        ips = _IP_RE.findall(rest)
        # Hostnames: tokens that look like names but are not pure RTT numbers or
        # the "ms" unit; drop anything already captured as an IP.
        hosts = []
        for token in re.split(r"[\s()]+", rest):
            if not token or token.lower() == "ms":
                continue
            if _RTT_RE.fullmatch(token + " ms") or re.fullmatch(r"\d+(\.\d+)?", token):
                continue
            if token in ips:
                continue
            if _HOST_RE.fullmatch(token) and re.search(r"[A-Za-z]", token):
                hosts.append(token)
        hops.append({
            "hop": hop_no,
            "hosts": hosts,
            "ips": ips,
            "rtts": rtts,
            "timeout": not rtts and "*" in rest,
        })
    return hops


def _trace_binary():
    """Return (argv_prefix, name) for the platform's tracer, or raise."""
    if sys.platform.startswith("win"):
        exe = shutil.which("tracert")
        if exe:
            return [exe], "tracert"
    else:
        for name in ("traceroute", "tracepath"):
            exe = shutil.which(name)
            if exe:
                return [exe], name
    raise NetScopeError(
        "No traceroute program found (install 'traceroute' on Linux/macOS; "
        "'tracert' ships with Windows).")


def traceroute(host, max_hops=30, timeout=2.0):
    """Trace the route to *host* and return a list of hop dicts.

    Raises :class:`NetScopeError` if no tracer binary is available or the tool
    errors out before producing any hops.
    """
    if not host or not str(host).strip():
        raise NetScopeError("No host given.")
    host = str(host).strip()
    prefix, name = _trace_binary()
    cmd = list(prefix)
    if name == "tracert":
        cmd += ["-h", str(int(max_hops)), "-w",
                str(int(max(1, timeout) * 1000)), host]
    elif name == "tracepath":
        cmd += ["-m", str(int(max_hops)), host]
    else:  # traceroute
        cmd += ["-m", str(int(max_hops)), "-w",
                str(int(max(1, timeout))), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=max(10.0, max_hops * timeout + 10))
    except FileNotFoundError as exc:
        raise NetScopeError(f"{name} was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise NetScopeError(f"traceroute timed out for {host!r}.") from exc
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    hops = parse_trace_output(out)
    if not hops:
        raise NetScopeError(
            f"traceroute produced no hops for {host!r}. {out.strip()[:200]}")
    return hops
