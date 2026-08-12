# NetScope

A fast, **offline**, **100% open-source** network diagnostics toolkit for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/net-scope).

> **100% AI-built and open source.** Apache-2.0.

## What it does

A desktop network toolkit: ping and traceroute with charts, TCP/UDP port scanning, DNS lookups and record inspection, WHOIS, reverse-DNS, a subnet calculator, and LAN device discovery. Everything runs locally; pairs with PrivateFirewall and Infra Monitor.

## Install

Download **`NetScope-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/net-scope) or the [GitHub release](https://github.com/quickpod/net-scope/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python net_scope_app.py          # GUI
python -m netscope --help    # CLI
```


## Features

- **Ping** — latency to any host via the OS `ping`, with an automatic
  dependency-free TCP-connect probe when ICMP is blocked. The GUI draws a live
  RTT chart as replies arrive.
- **Traceroute** — the hop-by-hop path to a host (`traceroute`/`tracert`), with
  per-hop RTTs; degrades cleanly when the system tracer is absent.
- **Port scan** — non-blocking TCP-connect scan (no root, no raw sockets). A
  built-in common-ports preset, or your own list/ranges like `22,80,8000-8010`.
- **DNS** — forward lookups for any record type, a one-shot sweep of all common
  types, reverse-DNS (PTR), and a resolver benchmark that races several DNS
  servers. Powered by dnspython.
- **WHOIS** — registration details for a domain or IP straight from the registry
  over port 43, following one referral for the richer record.
- **Subnet calculator** — instant IPv4/IPv6 CIDR math: network, broadcast, mask,
  wildcard, usable host range and count (handles `/31`, `/32` and IPv6).
- **LAN discovery** — list live hosts from the system ARP table, or a threaded
  TCP-connect sweep of the local `/24`.

Everything runs locally and offline. Each tool is available in both the tkinter
GUI and the `netscope` CLI, backed by the same tested core library.

## CLI examples

```sh
netscope ping 1.1.1.1 -c 10             # ICMP ping (TCP fallback if blocked)
netscope ping example.com -m tcp --port 443
netscope trace quickopen.ai             # traceroute
netscope scan 127.0.0.1 --ports common  # scan the common-ports preset
netscope scan 198.51.100.5 --ports 22,80,8000-8010
netscope check 198.51.100.5 443             # single port (exit 0 open, 2 closed)
netscope dns quickopen.ai --type MX     # DNS lookup
netscope records quickopen.ai           # all common record types
netscope reverse 1.1.1.1                # reverse DNS
netscope benchmark --name example.com 1.1.1.1 8.8.8.8 9.9.9.9
netscope whois quickopen.ai             # WHOIS a domain or IP
netscope subnet 192.168.1.0/24 --split 26
netscope discover                       # read the ARP table
netscope discover --sweep --network 192.168.1.0/24
```

(Run the same commands as `python -m netscope ...` from a source checkout.)

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
