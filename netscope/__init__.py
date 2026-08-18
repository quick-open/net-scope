"""netscope -- a permissively-licensed network-diagnostics toolkit.

Pure-stdlib probes (``socket``/``subprocess``/``ipaddress``) plus ``dnspython``
for DNS.  No scapy, no raw sockets, no root.  Every public function raises
:class:`NetScopeError` (and only that) on an expected failure, so the CLI and
the tkinter GUI share a single exception type::

    from netscope import ping, scan_ports, subnet_info
    print(ping("1.1.1.1", count=2))
    print(subnet_info("192.0.2.0/24"))

The GUI (``netscope.gui``) and CLI (``python -m netscope``) both build only on
these functions and never re-implement the logic.
"""

from __future__ import annotations

from .errors import NetScopeError
from .ping import ping, os_ping, tcp_ping, parse_ping_output
from .trace import traceroute, parse_trace_output
from .ports import scan_ports, check_port, parse_ports, COMMON_PORTS
from .dns_tools import (
    resolve,
    reverse,
    all_records,
    dns_benchmark,
    COMMON_RECORD_TYPES,
)
from .whois_tool import whois, pick_whois_server
from .subnet import subnet_info, parse_network, subnets, contains
from .discover import (
    arp_table,
    parse_arp,
    sweep,
    local_ipv4,
    local_network,
)

__version__ = "1.0.5"

__all__ = [
    "NetScopeError",
    "ping", "os_ping", "tcp_ping", "parse_ping_output",
    "traceroute", "parse_trace_output",
    "scan_ports", "check_port", "parse_ports", "COMMON_PORTS",
    "resolve", "reverse", "all_records", "dns_benchmark", "COMMON_RECORD_TYPES",
    "whois", "pick_whois_server",
    "subnet_info", "parse_network", "subnets", "contains",
    "arp_table", "parse_arp", "sweep", "local_ipv4", "local_network",
]
