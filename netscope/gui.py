#!/usr/bin/env python3
r"""NetScope -- an Aura (QuickOpen design system) GUI on top of the ``netscope`` API.

A single Aura window: a left sidebar of diagnostic sections (Ping, Traceroute,
Port scan, DNS lookup, All records, Reverse DNS, Resolver benchmark, WHOIS,
Subnet calculator, LAN discovery, About) and a swappable main panel.  Every
operation calls the tested core library (never re-implements the probe) and runs
on a background thread so the UI stays responsive; results are marshalled back
with ``self.after`` and reported in the Aura status bar -- a summary line on
success, or the ``NetScopeError`` message (never a raw traceback) on failure.

Design goals baked in here (mirrors the QuickOpen house style):
  * built on the vendored ``netscope/aura.py`` design system, which layers the
    quickopen.ai look (deep space + light) over CustomTkinter.  Runtime deps:
    ``customtkinter`` (+ ``darkdetect``) -- declared in requirements.txt; the
    PyInstaller build adds ``--collect-all customtkinter``.
  * the ping panel still draws a live RTT chart on a plain ``Canvas`` (tracked
    for theme flips); the port scanner / benchmark / discovery still fill
    ``Treeview`` tables; the subnet calculator still updates instantly with no
    thread at all.
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a message, returns 0) with no display OR
    with customtkinter missing.
  * Frozen-exe safe: bundled assets are resolved via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter/customtkinter are imported lazily inside main()/build_app so that
# merely importing this module (e.g. during packaging or on a headless CI box)
# never fails.  The netscope core is imported the same way.

APP_NAME = "NetScope"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "NetScope — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"
ACCENT = "#2f5fe0"      # net-scope UI accent (QuickOpen blue)

# Sidebar sections: (tool_id, label, DejaVu-safe nav glyph).  tool_id maps to a
# _panel_<id> builder method.  Glyphs are verified present in DejaVu Sans.
SECTIONS = [
    ("ping", "Ping", "◷"),
    ("trace", "Traceroute", "⇄"),
    ("scan", "Port scan", "⊞"),
    ("dns", "DNS lookup", "⚲"),
    ("records", "All records", "▤"),
    ("reverse", "Reverse DNS", "⇅"),
    ("benchmark", "Resolver benchmark", "◵"),
    ("whois", "WHOIS", "▦"),
    ("subnet", "Subnet calculator", "⬢"),
    ("discover", "LAN discovery", "◎"),
    ("about", "About", "ℹ"),
]

TOOL_DESCRIPTIONS = {
    "ping": "Measure round-trip latency (system ping, or a TCP-connect probe "
            "when ICMP is blocked). Watch the live RTT chart.",
    "trace": "Show the network path to a host, hop by hop, with per-hop RTTs.",
    "scan": "TCP-connect scan of a host — a common-ports preset or your own "
            "list/ranges. Open ports appear in the table.",
    "dns": "Resolve a name for one record type (A, AAAA, MX, TXT, ...).",
    "records": "Sweep many record types for a name at once.",
    "reverse": "Reverse-resolve an IP address to its PTR hostname(s).",
    "benchmark": "Time the same lookup across several DNS resolvers.",
    "whois": "Registration details for a domain or IP, straight from the "
             "registry over port 43.",
    "subnet": "Instant subnet math for an IPv4/IPv6 CIDR — network, broadcast, "
              "mask, host range and count.",
    "discover": "Find live hosts on your LAN via the ARP table or a TCP sweep "
                "of the local /24.",
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build.

    For a frozen exe we look only at ``sys._MEIPASS`` and the executable's own
    directory (never ``__file__``).  From source we also consult the package
    dir, the repo root and the CWD.  Returns an absolute path or ``None``.
    """
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                # noqa: S606 - intended
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports.

    Kept inside a function so this module imports cleanly without a display
    (and without customtkinter installed).
    """
    import tkinter as tk
    from tkinter import ttk
    import customtkinter as ctk

    from . import aura, guiconfig
    from .errors import NetScopeError
    # NOTE: netscope/__init__ rebinds the package attribute 'ping' to the ping()
    # FUNCTION (``from .ping import ping``), so 'from . import ping' returns the
    # function, not the module -- which is exactly what we call below.
    from . import (
        ping as ping_mod,
        traceroute,
        scan_ports,
        parse_ports,
        resolve,
        reverse,
        all_records,
        dns_benchmark,
        COMMON_RECORD_TYPES,
        whois,
        subnet_info,
        subnets,
        arp_table,
        sweep,
        local_network,
    )

    # tk fonts used only for the raw tk.Text output areas + the Canvas chart
    # (all other typography comes from aura.font()).  Aura's family is
    # DejaVu Sans on Linux/Xvfb, Segoe UI on Windows.
    FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
    MONO = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"

    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=guiconfig.get_theme(),
                icon_png=asset_path("net-scope.png"), version=APP_VERSION,
                tagline="offline toolkit",
                on_theme_change=guiconfig.set_theme,
                size=(1080, 680), min_size=(900, 560))

            self._busy = False
            self._host_vars = {}       # section id -> host StringVar (for Recent)
            self._img_refs_gui = []    # keep PhotoImage refs alive (not AuraApp's)
            self._ping_stop = threading.Event()
            self._ping_rtts = []       # live chart data for the ping panel
            self._ping_canvas = None

            self._set_icon()
            self._build_menu()
            for sid, label, glyph in SECTIONS:
                self.add_section(sid, label, glyph,
                                 lambda frame, s=sid: self._build_panel(frame, s))
            self.show("ping")
            self.set_status("Ready")
            self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- assets / icon (window + taskbar; sidebar icon is AuraApp's job)
        def _set_icon(self):
            try:
                ico = asset_path("net-scope.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("net-scope.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs_gui.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- native menu (auto-themed; theme toggle also lives in the sidebar)
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            self._recent_menu = tk.Menu(filem, tearoff=0)
            filem.add_cascade(label="Recent targets", menu=self._recent_menu)
            self._fill_recent_menu()
            filem.add_separator()
            filem.add_command(label="Exit", command=self._on_close)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(
                label="Toggle dark mode",
                command=lambda: self.set_theme(
                    "light" if self.theme == "dark" else "dark"))
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=lambda: self.show("about"))
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)

        def _fill_recent_menu(self):
            self._recent_menu.delete(0, "end")
            recent = guiconfig.get_recent()
            if not recent:
                self._recent_menu.add_command(label="(none yet)", state="disabled")
                return
            for target in recent:
                self._recent_menu.add_command(
                    label=target,
                    command=(lambda t=target: self._use_recent(t)))
            self._recent_menu.add_separator()
            self._recent_menu.add_command(label="Clear list",
                                          command=self._clear_recent)

        def _use_recent(self, target):
            """Drop a remembered target into the current panel's host field."""
            var = self._host_vars.get(self.active_section)
            if var is not None:
                var.set(target)

        def _clear_recent(self):
            guiconfig.clear_recent()
            self._fill_recent_menu()

        def remember_target(self, target):
            if target and str(target).strip():
                guiconfig.add_recent(str(target).strip())
                self._fill_recent_menu()

        # ---- section framing / theme --------------------------------------
        def show(self, sid):
            # stop any live ping when navigating away from (or into) a panel
            self._ping_stop.set()
            super().show(sid)
            self.set_status("Ready")

        def set_theme(self, theme):
            super().set_theme(theme)
            # the tracked Canvas bg flips automatically; redraw its content so
            # the chart lines/labels pick up the new palette too.
            if self._ping_canvas is not None:
                self._draw_ping_chart()

        def _build_panel(self, frame, sid):
            desc = TOOL_DESCRIPTIONS.get(sid)
            if desc:
                aura.Caption(frame, desc, wraplength=780,
                             justify="left").pack(anchor="w", pady=(0, 12))
            builder = getattr(self, "_panel_" + sid, None)
            if builder:
                builder(frame)

        # ---- background operation runner ----------------------------------
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors go to the Aura status bar (NetScopeError message, or a generic
            note), never as a traceback.  Refuses a second op while one is live.
            """
            if self._busy:
                self.set_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self.set_status(busy, kind="working")

            def run():
                try:
                    res, err = work(), None
                except NetScopeError as ex:
                    res, err = None, str(ex)
                except Exception as ex:  # never leak a traceback to the user
                    res, err = None, f"Unexpected error: {ex}"
                self.after(0, lambda: finish(res, err))

            def finish(res, err):
                self._busy = False
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self.set_error(err)
                    return
                try:
                    on_ok(res)
                except Exception as ex:
                    self.set_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- shared widgets -----------------------------------------------
        def _row(self, parent):
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", pady=4)
            return r

        def _lbl(self, parent, text, width=118):
            return ctk.CTkLabel(parent, text=text, font=aura.font(),
                                width=width, anchor="w")

        def _host_row(self, parent, sid, label="Host / IP", default=""):
            """A labelled entry whose var is remembered for the Recent menu."""
            row = self._row(parent)
            self._lbl(row, label).pack(side="left")
            var = tk.StringVar(value=default)
            ent = aura.AuraEntry(row, textvariable=var)
            ent.pack(side="left", fill="x", expand=True)
            self._host_vars[sid] = var
            return var

        def _make_output(self, parent, height=16):
            """A read-only monospaced Text area with scrollbars (theme-tracked)."""
            body = ctk.CTkFrame(parent, fg_color="transparent")
            body.pack(fill="both", expand=True, pady=(8, 0))
            txt = tk.Text(body, wrap="none", height=height, font=(MONO, 10),
                          borderwidth=0, relief="flat")
            sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
            xb = ttk.Scrollbar(parent, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=sb.set, xscrollcommand=xb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            xb.pack(fill="x")
            aura.track(txt, "text")
            return txt

        def _set_text(self, txt, content):
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", content)
            txt.configure(state="disabled")

        def _make_table(self, parent, columns, height=14):
            """A ttk.Treeview (auto-restyled by Aura) with an Aura scrollbar."""
            body = ctk.CTkFrame(parent, fg_color="transparent")
            body.pack(fill="both", expand=True, pady=(8, 0))
            cids = [c[0] for c in columns]
            tree = ttk.Treeview(body, columns=cids, show="headings",
                                 selectmode="browse", height=height)
            for cid, label, width, anchor in columns:
                tree.heading(cid, text=aura.spaced(label), anchor="w")
                tree.column(cid, width=width, anchor=anchor)
            sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)
            return tree

        # ===================================================================
        # PANELS
        # ===================================================================

        # ---------- Ping (with live RTT chart) ----------
        def _panel_ping(self, parent):
            host = self._host_row(parent, "ping", default="quickopen.ai")
            row = self._row(parent)
            self._lbl(row, "Count").pack(side="left")
            count = tk.StringVar(value="10")
            ttk.Spinbox(row, from_=1, to=100, textvariable=count,
                        width=6).pack(side="left")
            self._lbl(row, "Method", width=70).pack(side="left", padx=(16, 0))
            method = tk.StringVar(value="auto")
            aura.AuraCombo(row, variable=method, state="readonly", width=100,
                           values=["auto", "os", "tcp"]).pack(side="left")
            self._lbl(row, "TCP port", width=80).pack(side="left", padx=(16, 0))
            port = tk.StringVar(value="443")
            ttk.Spinbox(row, from_=1, to=65535, textvariable=port,
                        width=7).pack(side="left")

            btns = ctk.CTkFrame(parent, fg_color="transparent")
            btns.pack(fill="x", pady=8)
            run = aura.AuraButton(btns, "Start ping", kind="primary")
            run.pack(side="left")
            aura.AuraButton(btns, "Stop", kind="secondary",
                            command=lambda: self._ping_stop.set()).pack(
                side="left", padx=8)

            self._ping_canvas = tk.Canvas(parent, height=220, borderwidth=0,
                                          highlightthickness=0)
            self._ping_canvas.pack(fill="both", expand=True, pady=(8, 0))
            aura.track(self._ping_canvas, "canvas")
            self._ping_canvas.bind("<Configure>",
                                   lambda e: self._draw_ping_chart())

            def go():
                h = host.get().strip()
                if not h:
                    self.set_error("Enter a host or IP to ping.")
                    return
                try:
                    n = max(1, int(count.get()))
                    pr = int(port.get())
                except ValueError:
                    self.set_error("Count and port must be whole numbers.")
                    return
                self.remember_target(h)
                self._ping_rtts = []
                self._draw_ping_chart()
                self._start_ping(h, n, method.get(), pr, run)

            run.configure(command=go)
            self.after(60, self._draw_ping_chart)

        def _start_ping(self, host, count, method, port, button):
            if self._busy:
                self.set_error("Please wait — an operation is already running.")
                return
            self._busy = True
            self._ping_stop.clear()
            try:
                button.state(["disabled"])
            except Exception:
                pass
            self.set_status("pinging…", kind="working")
            sent = {"n": 0, "recv": 0}

            def worker():
                for _ in range(count):
                    if self._ping_stop.is_set():
                        break
                    try:
                        res = ping_mod(host, count=1, timeout=2.0,
                                       method=method, port=port)
                        rtt = res["rtts"][0] if res["rtts"] else None
                    except NetScopeError as ex:
                        self.after(0, lambda e=str(ex): self.set_error(e))
                        break
                    except Exception as ex:
                        self.after(0, lambda e=str(ex):
                                   self.set_error(f"Unexpected error: {e}"))
                        break
                    sent["n"] += 1
                    if rtt is not None:
                        sent["recv"] += 1
                    self.after(0, lambda r=rtt: self._ping_tick(r, sent))
                self.after(0, done)

            def done():
                self._busy = False
                try:
                    button.state(["!disabled"])
                except Exception:
                    pass
                lost = sent["n"] - sent["recv"]
                loss = (100.0 * lost / sent["n"]) if sent["n"] else 0.0
                if self._ping_rtts:
                    avg = sum(self._ping_rtts) / len(self._ping_rtts)
                    self.set_success(
                        f"{sent['recv']}/{sent['n']} replies, {loss:.0f}% loss, "
                        f"avg {avg:.2f} ms "
                        f"(min {min(self._ping_rtts):.2f} / "
                        f"max {max(self._ping_rtts):.2f})")
                elif sent["n"]:
                    self.set_error(f"No replies from {host} "
                                   f"({sent['n']} attempts, 100% loss).")
                else:
                    self.set_status("Stopped.")

            threading.Thread(target=worker, daemon=True).start()

        def _ping_tick(self, rtt, sent):
            if rtt is not None:
                self._ping_rtts.append(rtt)
            self.set_status(f"pinging… {sent['recv']}/{sent['n']}", kind="working")
            self._draw_ping_chart()

        def _draw_ping_chart(self):
            cv = self._ping_canvas
            if cv is None:
                return
            try:
                cv.delete("all")
            except Exception:
                return
            p = aura.P()
            w = cv.winfo_width() or 600
            h = cv.winfo_height() or 220
            pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 24
            x0, y0 = pad_l, pad_t
            x1, y1 = w - pad_r, h - pad_b
            # axes
            cv.create_line(x0, y1, x1, y1, fill=p["border2"])
            cv.create_line(x0, y0, x0, y1, fill=p["border2"])
            data = self._ping_rtts
            if not data:
                cv.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                               text="RTT chart — press Start ping",
                               fill=p["muted"], font=(FONT, 10))
                return
            hi = max(data)
            hi = hi if hi > 0 else 1.0
            top = hi * 1.15
            # gridlines + y labels
            for frac in (0.0, 0.5, 1.0):
                yy = y1 - (y1 - y0) * frac
                cv.create_line(x0, yy, x1, yy, fill=p["border"])
                cv.create_text(x0 - 6, yy, anchor="e",
                               text=f"{top * frac:.0f}", fill=p["muted"],
                               font=(FONT, 8))
            n = len(data)
            span = max(1, n - 1)
            pts = []
            for i, v in enumerate(data):
                xx = x0 + (x1 - x0) * (i / span if n > 1 else 0.5)
                yy = y1 - (y1 - y0) * (v / top)
                pts.append((xx, yy))
            if len(pts) > 1:
                flat = [c for xy in pts for c in xy]
                cv.create_line(*flat, fill=p["accent"], width=2, smooth=False)
            for xx, yy in pts:
                cv.create_oval(xx - 3, yy - 3, xx + 3, yy + 3,
                               fill=p["accent"], outline=p["surface"])
            cv.create_text(x1, y0, anchor="ne",
                           text=f"last {data[-1]:.2f} ms  ·  avg "
                                f"{sum(data) / len(data):.2f} ms",
                           fill=p["muted"], font=(FONT, 9))

        # ---------- Traceroute ----------
        def _panel_trace(self, parent):
            host = self._host_row(parent, "trace", default="quickopen.ai")
            row = self._row(parent)
            self._lbl(row, "Max hops").pack(side="left")
            hops = tk.StringVar(value="30")
            ttk.Spinbox(row, from_=1, to=64, textvariable=hops,
                        width=6).pack(side="left")
            run = aura.AuraButton(parent, "Trace route", kind="primary")
            run.pack(anchor="w", pady=8)
            out = self._make_output(parent)

            def go():
                h = host.get().strip()
                if not h:
                    self.set_error("Enter a host or IP.")
                    return
                try:
                    mh = int(hops.get())
                except ValueError:
                    self.set_error("Max hops must be a whole number.")
                    return
                self.remember_target(h)
                self._set_text(out, "Tracing… (this can take a while)\n")

                def ok(hop_list):
                    lines = [f"traceroute to {h} — {len(hop_list)} hops", ""]
                    for hop in hop_list:
                        if hop["timeout"]:
                            lines.append(f"{hop['hop']:>3}  * * *")
                            continue
                        where = " ".join(hop["hosts"] + hop["ips"]) or "?"
                        rtts = "  ".join(f"{r:.2f} ms" for r in hop["rtts"])
                        lines.append(f"{hop['hop']:>3}  {where:<40} {rtts}")
                    self._set_text(out, "\n".join(lines))
                    self.set_success(f"Traced {len(hop_list)} hop(s) to {h}.")

                self._bg(lambda: traceroute(h, max_hops=mh), ok, button=run)

            run.configure(command=go)

        # ---------- Port scan ----------
        def _panel_scan(self, parent):
            host = self._host_row(parent, "scan", default="127.0.0.1")
            row = self._row(parent)
            self._lbl(row, "Ports").pack(side="left")
            ports = tk.StringVar(value="common")
            aura.AuraEntry(row, textvariable=ports).pack(
                side="left", fill="x", expand=True)
            aura.Caption(parent,
                         "Use 'common' for the built-in preset, or a list like "
                         "22,80,443,8000-8010.").pack(anchor="w")
            run = aura.AuraButton(parent, "Scan ports", kind="primary")
            run.pack(anchor="w", pady=8)
            tree = self._make_table(parent, [
                ("port", "Port", 90, "e"),
                ("state", "State", 100, "center"),
                ("service", "Service", 220, "w"),
            ])

            def go():
                h = host.get().strip()
                if not h:
                    self.set_error("Enter a host or IP.")
                    return
                try:
                    port_list = parse_ports(ports.get())
                except NetScopeError as ex:
                    self.set_error(str(ex))
                    return
                self.remember_target(h)
                for i in tree.get_children():
                    tree.delete(i)

                def ok(results):
                    open_ports = [r for r in results if r["open"]]
                    for r in open_ports:
                        tree.insert("", "end", values=(
                            r["port"], "open", r["service"] or "—"))
                    if not open_ports:
                        tree.insert("", "end", values=("—", "none open", "—"))
                    self.set_success(
                        f"Scanned {len(results)} port(s) on {h}; "
                        f"{len(open_ports)} open.")

                self._bg(lambda: scan_ports(h, port_list, timeout=1.0), ok,
                         button=run)

            run.configure(command=go)

        # ---------- DNS lookup ----------
        def _panel_dns(self, parent):
            name = self._host_row(parent, "dns", "Name", default="quickopen.ai")
            row = self._row(parent)
            self._lbl(row, "Type").pack(side="left")
            rtype = tk.StringVar(value="A")
            aura.AuraCombo(row, variable=rtype, width=110, state="readonly",
                           values=list(COMMON_RECORD_TYPES)).pack(side="left")
            run = aura.AuraButton(parent, "Resolve", kind="primary")
            run.pack(anchor="w", pady=8)
            out = self._make_output(parent)

            def go():
                n = name.get().strip()
                if not n:
                    self.set_error("Enter a name to resolve.")
                    return
                self.remember_target(n)

                def ok(answers):
                    self._set_text(out, "\n".join(answers) or "(no answers)")
                    self.set_success(
                        f"{n} {rtype.get()} → {len(answers)} answer(s).")

                self._bg(lambda: resolve(n, rtype.get()), ok, button=run)

            run.configure(command=go)

        # ---------- All records ----------
        def _panel_records(self, parent):
            name = self._host_row(parent, "records", "Name",
                                  default="quickopen.ai")
            run = aura.AuraButton(parent, "Look up all records", kind="primary")
            run.pack(anchor="w", pady=8)
            out = self._make_output(parent)

            def go():
                n = name.get().strip()
                if not n:
                    self.set_error("Enter a name.")
                    return
                self.remember_target(n)

                def ok(recs):
                    if not recs:
                        self._set_text(out, "(no records found)")
                        self.set_success(f"No records for {n}.")
                        return
                    lines = []
                    for rtype, answers in recs.items():
                        for ans in answers:
                            lines.append(f"{rtype:<6} {ans}")
                    self._set_text(out, "\n".join(lines))
                    self.set_success(
                        f"{n}: {sum(len(v) for v in recs.values())} record(s) "
                        f"across {len(recs)} type(s).")

                self._bg(lambda: all_records(n), ok, button=run)

            run.configure(command=go)

        # ---------- Reverse DNS ----------
        def _panel_reverse(self, parent):
            ip = self._host_row(parent, "reverse", "IP address",
                                default="192.0.2.1")
            run = aura.AuraButton(parent, "Reverse lookup", kind="primary")
            run.pack(anchor="w", pady=8)
            out = self._make_output(parent, height=8)

            def go():
                v = ip.get().strip()
                if not v:
                    self.set_error("Enter an IP address.")
                    return
                self.remember_target(v)

                def ok(names):
                    self._set_text(out, "\n".join(names) or "(no PTR record)")
                    self.set_success(f"{v} → {len(names)} name(s).")

                self._bg(lambda: reverse(v), ok, button=run)

            run.configure(command=go)

        # ---------- Resolver benchmark ----------
        def _panel_benchmark(self, parent):
            name = self._host_row(parent, "benchmark", "Name",
                                  default="example.com")
            row = self._row(parent)
            self._lbl(row, "Resolvers").pack(side="left")
            resolvers = tk.StringVar(value=", ".join(guiconfig.get_resolvers()))
            aura.AuraEntry(row, textvariable=resolvers).pack(
                side="left", fill="x", expand=True)
            run = aura.AuraButton(parent, "Benchmark", kind="primary")
            run.pack(anchor="w", pady=8)
            tree = self._make_table(parent, [
                ("resolver", "Resolver", 180, "w"),
                ("ms", "ms", 100, "e"),
                ("result", "Result", 280, "w"),
            ], height=10)

            def go():
                n = name.get().strip() or "example.com"
                ips = [r.strip() for r in resolvers.get().replace(";", ",").split(",")
                       if r.strip()]
                if not ips:
                    self.set_error("Enter at least one resolver IP.")
                    return
                for i in tree.get_children():
                    tree.delete(i)

                def ok(rows):
                    for r in rows:
                        if r["ok"]:
                            tree.insert("", "end", values=(
                                r["resolver"], f"{r['ms']:.2f}",
                                ", ".join(r["answers"])))
                        else:
                            tree.insert("", "end", values=(
                                r["resolver"], "FAIL", r["error"]))
                    ok_rows = [r for r in rows if r["ok"]]
                    if ok_rows:
                        best = ok_rows[0]
                        self.set_success(
                            f"Fastest: {best['resolver']} at {best['ms']:.2f} ms.")
                    else:
                        self.set_error("No resolver answered.")

                self._bg(lambda: dns_benchmark(ips, name=n), ok, button=run)

            run.configure(command=go)

        # ---------- WHOIS ----------
        def _panel_whois(self, parent):
            q = self._host_row(parent, "whois", "Domain / IP",
                               default="quickopen.ai")
            follow = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(parent, text="Follow registry referral",
                            variable=follow, font=aura.font()).pack(
                anchor="w", pady=(2, 0))
            run = aura.AuraButton(parent, "WHOIS lookup", kind="primary")
            run.pack(anchor="w", pady=8)
            out = self._make_output(parent)

            def go():
                v = q.get().strip()
                if not v:
                    self.set_error("Enter a domain or IP.")
                    return
                self.remember_target(v)
                self._set_text(out, "Querying WHOIS…")

                def ok(text):
                    self._set_text(out, text.rstrip() or "(empty response)")
                    self.set_success(f"WHOIS for {v} retrieved.")

                self._bg(lambda: whois(v, follow=follow.get()), ok, button=run)

            run.configure(command=go)

        # ---------- Subnet calculator (instant, no thread) ----------
        def _panel_subnet(self, parent):
            row = self._row(parent)
            self._lbl(row, "CIDR").pack(side="left")
            cidr = tk.StringVar(value="192.0.2.0/24")
            aura.AuraEntry(row, textvariable=cidr).pack(
                side="left", fill="x", expand=True)
            aura.Caption(parent,
                         "IPv4 or IPv6, e.g. 198.51.100.0/24, 192.0.2.10/24, "
                         "2001:db8::/48. Updates as you type.").pack(anchor="w")
            out = self._make_output(parent, height=14)

            def recompute(*_):
                text = cidr.get().strip()
                if not text:
                    self._set_text(out, "")
                    self.set_status("Ready")
                    return
                try:
                    info = subnet_info(text)
                except NetScopeError as ex:
                    self._set_text(out, "")
                    self.set_error(str(ex))
                    return
                labels = [
                    ("CIDR", "cidr"), ("IP version", "version"),
                    ("Network address", "network_address"),
                    ("Broadcast address", "broadcast_address"),
                    ("Netmask", "netmask"), ("Hostmask (wildcard)", "hostmask"),
                    ("Prefix length", "prefixlen"),
                    ("Total addresses", "num_addresses"),
                    ("Usable hosts", "num_usable_hosts"),
                    ("Host range", "host_range"),
                    ("Private range", "is_private"),
                ]
                lines = []
                for label, key in labels:
                    val = info.get(key)
                    lines.append(f"{label:<20} {'-' if val is None else val}")
                self._set_text(out, "\n".join(lines))
                self.set_success(
                    f"{info['cidr']} — {info['num_usable_hosts']} usable host(s).")

            cidr.trace_add("write", recompute)
            self.after(60, recompute)

        # ---------- LAN discovery ----------
        def _panel_discover(self, parent):
            mode = tk.StringVar(value="arp")
            box = aura.Card(parent, title="Method")
            box.pack(fill="x", pady=(0, 8))
            ctk.CTkRadioButton(box.body, text="Read system ARP table (instant)",
                               value="arp", variable=mode,
                               font=aura.font()).pack(anchor="w", pady=2)
            r2 = ctk.CTkFrame(box.body, fg_color="transparent")
            r2.pack(fill="x", pady=2)
            ctk.CTkRadioButton(r2, text="TCP-connect sweep of", value="sweep",
                               variable=mode, font=aura.font()).pack(side="left")
            net = tk.StringVar()
            aura.AuraEntry(r2, textvariable=net, width=200).pack(
                side="left", padx=8)
            aura.Caption(r2, "(blank = local /24)").pack(side="left")
            run = aura.AuraButton(parent, "Discover hosts", kind="primary")
            run.pack(anchor="w", pady=8)
            tree = self._make_table(parent, [
                ("ip", "IP address", 180, "w"),
                ("detail", "MAC / open ports", 360, "w"),
            ])

            def go():
                for i in tree.get_children():
                    tree.delete(i)
                if mode.get() == "sweep":
                    target = net.get().strip() or None

                    def work():
                        return sweep(target)

                    def ok(rows):
                        for r in rows:
                            tree.insert("", "end", values=(
                                r["ip"], "ports: " + ",".join(
                                    str(p) for p in r["open_ports"])))
                        if not rows:
                            tree.insert("", "end",
                                        values=("—", "no hosts responded"))
                        self.set_success(f"Sweep found {len(rows)} live host(s).")

                    self._bg(work, ok, button=run, busy="Sweeping…")
                else:
                    def ok(rows):
                        for r in rows:
                            detail = r["mac"] or "(incomplete)"
                            if r["host"]:
                                detail += f"  {r['host']}"
                            tree.insert("", "end", values=(r["ip"], detail))
                        if not rows:
                            tree.insert("", "end",
                                        values=("—", "ARP table empty"))
                        self.set_success(
                            f"ARP table: {len(rows)} entr(y/ies).")

                    self._bg(arp_table, ok, button=run)

            run.configure(command=go)

        # ---------- About ----------
        def _panel_about(self, parent):
            card = aura.Card(parent, title="About NetScope")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=560,
                text="A fast, fully-offline network toolkit — ping, "
                     "traceroute, port scan, DNS, WHOIS, reverse-DNS, a "
                     "subnet calculator and LAN discovery.\n\n"
                     "100% AI-built, open source, published on QuickOpen. "
                     "Nothing is ever uploaded anywhere.").pack(anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Built on the Python "
                         "standard library plus dnspython.").pack(
                anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai", kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

        # ---- shutdown
        def _on_close(self):
            self._ping_stop.set()
            self.destroy()

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server) OR without customtkinter installed, it
    prints a friendly note and returns 0 instead of raising.
    """
    try:
        import tkinter as tk
    except Exception as exc:  # tkinter missing entirely
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    try:
        App = build_app()
        app = App()
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the "
              f"GUI here ({exc}). This app is intended for the Windows desktop.")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
