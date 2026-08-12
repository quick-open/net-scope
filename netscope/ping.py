"""Latency probing.

Two strategies, both driven through :func:`ping`:

* the OS ``ping`` binary (parsed by the pure, unit-testable
  :func:`parse_ping_output`), which measures true ICMP round-trips; and
* a dependency-free **TCP-connect** fallback (:func:`tcp_ping`) that times a
  handshake to a port -- handy when ICMP is blocked or the binary is missing,
  and the only mode that works without elevated privileges everywhere.

Every function returns the same shaped dict so the CLI and GUI treat them
alike.  :func:`parse_ping_output` never touches the network, so tests feed it
captured Windows/Linux/macOS ``ping`` transcripts.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time

from .errors import NetScopeError

# RTT like "time=12.3 ms", "time=12ms", "time<1ms" (Windows sub-millisecond).
# Group 1 is the operator ("=" or "<"), group 2 the value; "<1ms" reads as 0.0.
_RTT_RE = re.compile(r"time([=<])\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
# Summary line: "min/avg/max/mdev = 0.1/0.2/0.3/0.0 ms" (Linux/macOS).
_SUMMARY_RE = re.compile(
    r"=\s*(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)"
    r"(?:/(\d+(?:\.\d+)?))?\s*ms")
# Packet stats, tolerant across platforms.
_TX_RX_RE = re.compile(
    r"(\d+)\s+packets? (?:transmitted|sent).*?(\d+)\s+(?:received|packets? received)",
    re.IGNORECASE | re.DOTALL)
_WIN_TX_RX_RE = re.compile(
    r"Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)", re.IGNORECASE)


def parse_ping_output(text):
    """Parse OS ``ping`` output into a summary dict. Pure; no I/O.

    Returns ``{"rtts": [floats ms], "transmitted": int, "received": int,
    "loss_pct": float, "min": float|None, "avg": ..., "max": ..., "mdev": ...}``.
    Works on Linux, macOS and Windows ``ping``.  A ``time<1ms`` sample counts as
    a real reply with an RTT of ``0.0`` ms.
    """
    text = text or ""
    rtts = [(0.0 if m.group(1) == "<" else float(m.group(2)))
            for m in _RTT_RE.finditer(text)]

    transmitted = received = None
    m = _TX_RX_RE.search(text)
    if m:
        transmitted, received = int(m.group(1)), int(m.group(2))
    else:
        m = _WIN_TX_RX_RE.search(text)
        if m:
            transmitted, received = int(m.group(1)), int(m.group(2))

    if received is None:
        received = len(rtts)
    if transmitted is None:
        transmitted = received

    loss = 0.0
    if transmitted:
        loss = round(100.0 * (transmitted - received) / transmitted, 1)

    stats = {"min": None, "avg": None, "max": None, "mdev": None}
    sm = _SUMMARY_RE.search(text)
    if sm:
        stats["min"] = float(sm.group(1))
        stats["avg"] = float(sm.group(2))
        stats["max"] = float(sm.group(3))
        stats["mdev"] = float(sm.group(4)) if sm.group(4) else None
    elif rtts:
        stats["min"] = min(rtts)
        stats["max"] = max(rtts)
        stats["avg"] = round(sum(rtts) / len(rtts), 3)

    return {
        "rtts": rtts,
        "transmitted": transmitted,
        "received": received,
        "loss_pct": loss,
        **stats,
    }


def _ping_command(host, count, timeout):
    """Build the platform-appropriate ``ping`` argv."""
    if sys.platform.startswith("win"):
        # -n count, -w per-reply timeout in milliseconds.
        return ["ping", "-n", str(count), "-w",
                str(int(max(1, timeout) * 1000)), host]
    if sys.platform == "darwin":
        # -c count, -t total timeout (seconds).
        return ["ping", "-c", str(count), "-t",
                str(int(max(1, timeout * count))), host]
    # Linux / BSD: -c count, -w overall deadline (s), -W per-reply timeout (s).
    return ["ping", "-c", str(count), "-w",
            str(int(max(1, timeout * count))), "-W",
            str(int(max(1, timeout))), host]


def os_ping(host, count=4, timeout=2.0):
    """Run the OS ``ping`` binary and return a parsed summary dict.

    Raises :class:`NetScopeError` if the binary is missing or the host is
    plainly unreachable (100% loss is *not* an error -- it is a valid result).
    Adds ``host`` and ``method="os"`` to the parsed dict.
    """
    if not host or not str(host).strip():
        raise NetScopeError("No host given.")
    cmd = _ping_command(str(host).strip(), int(count), float(timeout))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=max(5.0, timeout * count + 5))
    except FileNotFoundError as exc:
        raise NetScopeError("The system 'ping' command was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise NetScopeError(f"ping timed out for {host!r}.") from exc
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    result = parse_ping_output(out)
    if result["received"] == 0 and result["transmitted"] == 0:
        # Nothing parseable at all -> treat as a hard failure (bad host, etc.).
        raise NetScopeError(
            f"ping produced no result for {host!r} "
            f"(exit {proc.returncode}). {out.strip()[:200]}")
    result["host"] = str(host).strip()
    result["method"] = "os"
    return result


def tcp_ping(host, count=4, timeout=2.0, port=443):
    """Dependency-free latency probe: time TCP connects to *host:port*.

    Returns the same dict shape as :func:`parse_ping_output` with
    ``method="tcp"`` and the probed ``port``.  A connect that succeeds *or* is
    actively refused still yields an RTT (the host answered); only timeouts /
    unreachable count as loss.  Never needs root.
    """
    if not host or not str(host).strip():
        raise NetScopeError("No host given.")
    host = str(host).strip()
    try:
        infos = socket.getaddrinfo(host, int(port), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise NetScopeError(f"Cannot resolve host {host!r}: {exc}") from exc
    family, _t, _p, _c, sockaddr = infos[0]

    rtts = []
    transmitted = received = 0
    for _ in range(int(count)):
        transmitted += 1
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(max(0.05, float(timeout)))
        start = time.perf_counter()
        try:
            rc = sock.connect_ex(sockaddr)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            # 0 == connected; ECONNREFUSED means the host replied (reachable).
            if rc == 0 or rc in (111, 61, 10061):
                rtts.append(round(elapsed_ms, 3))
                received += 1
        except OSError:
            pass
        finally:
            sock.close()

    loss = round(100.0 * (transmitted - received) / transmitted, 1) if transmitted else 0.0
    stats = {"min": None, "avg": None, "max": None, "mdev": None}
    if rtts:
        stats["min"] = min(rtts)
        stats["max"] = max(rtts)
        stats["avg"] = round(sum(rtts) / len(rtts), 3)
    return {
        "rtts": rtts, "transmitted": transmitted, "received": received,
        "loss_pct": loss, "host": host, "method": "tcp", "port": int(port),
        **stats,
    }


def ping(host, count=4, timeout=2.0, method="auto", port=443):
    """Ping *host*, returning a summary dict.

    ``method="os"`` uses the OS binary, ``"tcp"`` uses :func:`tcp_ping`, and
    ``"auto"`` (default) tries the OS binary and transparently falls back to the
    TCP probe if it is unavailable.
    """
    if method == "tcp":
        return tcp_ping(host, count=count, timeout=timeout, port=port)
    if method == "os":
        return os_ping(host, count=count, timeout=timeout)
    try:
        return os_ping(host, count=count, timeout=timeout)
    except NetScopeError:
        return tcp_ping(host, count=count, timeout=timeout, port=port)
