"""Command-line interface: ``python -m netscope <command> ...``.

Thin argparse wrapper over the :mod:`netscope` API.  Every command catches
:class:`NetScopeError` and exits cleanly (status 1, a one-line ``error:`` on
stderr) instead of dumping a traceback.
"""

from __future__ import annotations

import argparse
import sys

from . import (
    NetScopeError,
    all_records,
    arp_table,
    check_port,
    dns_benchmark,
    local_network,
    parse_ports,
    ping,
    resolve,
    reverse,
    scan_ports,
    subnet_info,
    subnets,
    sweep,
    traceroute,
    whois,
)
from .guiconfig import DEFAULT_RESOLVERS


# --- command handlers -------------------------------------------------------


def cmd_ping(a):
    res = ping(a.host, count=a.count, timeout=a.timeout, method=a.method,
               port=a.port)
    method = res.get("method")
    label = f"TCP:{res.get('port')}" if method == "tcp" else "ICMP"
    print(f"PING {res['host']}  ({label})")
    for i, rtt in enumerate(res["rtts"], 1):
        print(f"  reply {i}: {rtt:.2f} ms")
    print(f"  {res['transmitted']} sent, {res['received']} received, "
          f"{res['loss_pct']}% loss")
    if res.get("avg") is not None:
        print(f"  rtt min/avg/max = {res['min']:.2f}/{res['avg']:.2f}/"
              f"{res['max']:.2f} ms")


def cmd_trace(a):
    hops = traceroute(a.host, max_hops=a.max_hops, timeout=a.timeout)
    print(f"traceroute to {a.host}, {len(hops)} hops")
    for hop in hops:
        if hop["timeout"]:
            print(f"{hop['hop']:>3}  * * *")
            continue
        where = " ".join(hop["hosts"] + hop["ips"]) or "?"
        rtts = "  ".join(f"{r:.2f} ms" for r in hop["rtts"])
        print(f"{hop['hop']:>3}  {where}  {rtts}")


def cmd_scan(a):
    ports = parse_ports(a.ports)
    results = scan_ports(a.host, ports, timeout=a.timeout)
    open_ports = [r for r in results if r["open"]]
    print(f"Scanned {len(results)} port(s) on {a.host}; "
          f"{len(open_ports)} open:")
    for r in open_ports:
        svc = f"  ({r['service']})" if r["service"] else ""
        print(f"  {r['port']:>5}/tcp  open{svc}")
    if not open_ports:
        print("  (none open)")


def cmd_dns(a):
    answers = resolve(a.name, a.type)
    print(f"{a.name}  {a.type}:")
    for ans in answers:
        print(f"  {ans}")


def cmd_records(a):
    recs = all_records(a.name)
    if not recs:
        print(f"No records found for {a.name}.")
        return
    for rtype, answers in recs.items():
        for ans in answers:
            print(f"{a.name:<30} {rtype:<6} {ans}")


def cmd_reverse(a):
    names = reverse(a.ip)
    print(f"{a.ip}  PTR:")
    for name in names:
        print(f"  {name}")


def cmd_benchmark(a):
    resolvers = a.resolvers or DEFAULT_RESOLVERS
    rows = dns_benchmark(resolvers, name=a.name)
    print(f"DNS benchmark resolving {a.name} (fastest first):")
    for row in rows:
        if row["ok"]:
            print(f"  {row['resolver']:<16} {row['ms']:>8.2f} ms")
        else:
            print(f"  {row['resolver']:<16} {'FAIL':>8}  ({row['error']})")


def cmd_whois(a):
    print(whois(a.query, follow=not a.no_follow).rstrip())


def cmd_subnet(a):
    info = subnet_info(a.cidr)
    order = [
        ("CIDR", "cidr"), ("Version", "version"),
        ("Network", "network_address"), ("Broadcast", "broadcast_address"),
        ("Netmask", "netmask"), ("Hostmask", "hostmask"),
        ("Prefix", "prefixlen"), ("Addresses", "num_addresses"),
        ("Usable hosts", "num_usable_hosts"), ("Host range", "host_range"),
        ("Private", "is_private"),
    ]
    for label, key in order:
        val = info.get(key)
        if val is None:
            val = "-"
        print(f"  {label:<14} {val}")
    if a.split:
        print(f"  Split into /{a.split}:")
        for sn in subnets(a.cidr, a.split):
            print(f"    {sn}")


def cmd_check(a):
    is_open = check_port(a.host, a.port, timeout=a.timeout)
    print(f"{a.host}:{a.port}  {'open' if is_open else 'closed'}")
    return 0 if is_open else 2


def cmd_discover(a):
    if a.sweep:
        net = a.network or local_network()
        print(f"Sweeping {net} ...")
        live = sweep(net, timeout=a.timeout)
        if not live:
            print("  no responding hosts found.")
        for row in live:
            ports = ",".join(str(p) for p in row["open_ports"])
            print(f"  {row['ip']:<16} open: {ports}")
    else:
        table = arp_table()
        if not table:
            print("ARP table is empty.")
            return
        print(f"ARP table ({len(table)} entries):")
        for h in table:
            mac = h["mac"] or "(incomplete)"
            host = f"  {h['host']}" if h["host"] else ""
            print(f"  {h['ip']:<16} {mac}{host}")


# --- parser -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="netscope",
        description="NetScope -- offline network diagnostics "
                    "(ping, traceroute, port scan, DNS, whois, subnet, LAN).")
    p.add_argument("--version", action="version",
                   version=f"NetScope {_version()}")
    sub = p.add_subparsers(dest="command")
    sub.required = True

    def add(name, help_text, func):
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=func)
        return sp

    s = add("ping", "Ping a host (ICMP or TCP fallback)", cmd_ping)
    s.add_argument("host")
    s.add_argument("-c", "--count", type=int, default=4)
    s.add_argument("-t", "--timeout", type=float, default=2.0)
    s.add_argument("-m", "--method", choices=["auto", "os", "tcp"],
                   default="auto")
    s.add_argument("--port", type=int, default=443,
                   help="Port for the TCP probe (method tcp/auto-fallback).")

    s = add("trace", "Traceroute to a host", cmd_trace)
    s.add_argument("host")
    s.add_argument("--max-hops", type=int, default=30)
    s.add_argument("-t", "--timeout", type=float, default=2.0)

    s = add("scan", "TCP port scan", cmd_scan)
    s.add_argument("host")
    s.add_argument("--ports", default="common",
                   help="e.g. 22,80,8000-8010 or 'common' (default).")
    s.add_argument("-t", "--timeout", type=float, default=1.0)

    s = add("check", "Check a single TCP port (exit 0 open, 2 closed)",
            cmd_check)
    s.add_argument("host")
    s.add_argument("port", type=int)
    s.add_argument("-t", "--timeout", type=float, default=1.0)

    s = add("dns", "Resolve a name (A by default)", cmd_dns)
    s.add_argument("name")
    s.add_argument("--type", default="A", help="Record type: A, AAAA, MX, ...")

    s = add("records", "Look up many record types at once", cmd_records)
    s.add_argument("name")

    s = add("reverse", "Reverse-DNS an IP to hostnames", cmd_reverse)
    s.add_argument("ip")

    s = add("benchmark", "Benchmark DNS resolvers", cmd_benchmark)
    s.add_argument("--name", default="example.com")
    s.add_argument("resolvers", nargs="*",
                   help="Resolver IPs (default 1.1.1.1 8.8.8.8 9.9.9.9).")

    s = add("whois", "WHOIS a domain or IP", cmd_whois)
    s.add_argument("query")
    s.add_argument("--no-follow", action="store_true",
                   help="Do not chase the registry referral.")

    s = add("subnet", "Subnet calculator for a CIDR", cmd_subnet)
    s.add_argument("cidr")
    s.add_argument("--split", type=int,
                   help="Also split into subnets of this prefix length.")

    s = add("discover", "List LAN hosts (ARP table or TCP sweep)",
            cmd_discover)
    s.add_argument("--sweep", action="store_true",
                   help="TCP-connect sweep instead of reading the ARP table.")
    s.add_argument("--network", help="CIDR to sweep (default: local /24).")
    s.add_argument("-t", "--timeout", type=float, default=0.4)

    return p


def _version():
    try:
        from . import __version__
        return __version__
    except Exception:
        return "1.0.0"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
    except NetScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted.", file=sys.stderr)
        return 130
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
