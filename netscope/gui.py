#!/usr/bin/env python3
r"""NetScope -- a pure-stdlib tkinter GUI on top of the ``netscope`` API.

A single main window: a left sidebar of diagnostic tools (Reachability, Ports,
DNS, Info, LAN) and a main panel that swaps to the selected tool.  Every
operation calls the tested core library (never re-implements the probe) and runs
on a background thread so the UI stays responsive; results are marshalled back
with ``self.after`` and reported in a clear inline area -- a summary line on
success, or the ``NetScopeError`` message (never a raw traceback) on failure.

Design goals baked in here:
  * pure standard-library tkinter/ttk -- NO third-party GUI deps.  Dark mode is
    a ttk-style + palette swap.  The ping panel draws a live RTT chart on a
    plain ``Canvas``; the port scanner fills a ``Treeview`` table; the subnet
    calculator updates instantly with no thread at all.
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a message, returns 0) with no display.
  * Frozen-exe safe: bundled assets are resolved via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter is imported lazily inside main()/build_app so that merely
# importing this module (e.g. during packaging or on a headless CI box) never
# fails.  The netscope core is imported the same way.

APP_NAME = "NetScope"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "NetScope — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"

# ---- colour palettes (mirror the QuickOpen palette) -------------------------
PALETTES = {
    "light": {
        "bg": "#f5f7fa", "surface": "#ffffff", "text": "#141820",
        "muted": "#5b6472", "primary": "#2f5fe0", "primary_hi": "#2450c8",
        "entry": "#ffffff", "border": "#d5dae2", "sel": "#2f5fe0",
        "sel_fg": "#ffffff", "trough": "#e2e7ef", "ok": "#1f7a3d",
        "err": "#c0392b", "chart": "#2f5fe0", "grid": "#e2e7ef",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#1a1e24", "text": "#f1f3f7",
        "muted": "#9aa4b2", "primary": "#5b86f7", "primary_hi": "#7098ff",
        "entry": "#1a1e24", "border": "#2a2f38", "sel": "#5b86f7",
        "sel_fg": "#0f1115", "trough": "#2a2f38", "ok": "#5bd68a",
        "err": "#ff6b5e", "chart": "#5b86f7", "grid": "#2a2f38",
    },
}

# (category, [(tool_id, label), ...]) -- tool_id maps to a _panel_<id> method.
TOOL_TREE = [
    ("Reachability", [
        ("ping", "Ping"),
        ("trace", "Traceroute"),
    ]),
    ("Ports", [
        ("scan", "Port scan"),
    ]),
    ("DNS", [
        ("dns", "DNS lookup"),
        ("records", "All records"),
        ("reverse", "Reverse DNS"),
        ("benchmark", "Resolver benchmark"),
    ]),
    ("Info", [
        ("whois", "WHOIS"),
        ("subnet", "Subnet calculator"),
    ]),
    ("LAN", [
        ("discover", "LAN discovery"),
    ]),
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
# The app (built lazily; tkinter imported only inside build_app/main)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to a live tkinter import.

    Kept inside a function so this module imports cleanly without a display.
    """
    import tkinter as tk
    from tkinter import ttk

    from . import guiconfig
    from .errors import NetScopeError
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

    FONT = "Segoe UI"
    MONO = "Consolas"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(WINDOW_TITLE)
            self.geometry("1080x680")
            self.minsize(900, 560)

            self.theme = guiconfig.get_theme()
            self._busy = False
            self._panels = {}          # tool_id -> built frame (lazy)
            self._current = None
            self._tracked = []         # (tk_widget, role) for manual re-theming
            self._img_refs = []        # keep PhotoImage refs alive
            self._ping_stop = threading.Event()
            self._ping_rtts = []       # live chart data for the ping panel

            self._set_icon()
            self._build_menu()
            self._build_layout()
            self._apply_theme()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(50, self._select_first_tool)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("net-scope.ico")
                if ico:
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("net-scope.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- theming
        def track(self, widget, role):
            self._tracked.append((widget, role))

        def _pal(self):
            return PALETTES[self.theme]

        def _apply_theme(self):
            p = self._pal()
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self.configure(bg=p["bg"])
            style.configure(".", background=p["bg"], foreground=p["text"],
                            fieldbackground=p["entry"], bordercolor=p["border"],
                            font=(FONT, 10))
            style.configure("TFrame", background=p["bg"])
            style.configure("Sidebar.TFrame", background=p["surface"])
            style.configure("Card.TFrame", background=p["surface"])
            style.configure("TLabel", background=p["bg"], foreground=p["text"])
            style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                            font=(FONT, 15, "bold"))
            style.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"],
                            font=(FONT, 10))
            style.configure("Brand.TLabel", background=p["surface"],
                            foreground=p["text"], font=(FONT, 12, "bold"))
            style.configure("Ok.TLabel", background=p["bg"], foreground=p["ok"])
            style.configure("Err.TLabel", background=p["bg"], foreground=p["err"])
            style.configure("Status.TLabel", background=p["surface"],
                            foreground=p["muted"])
            style.configure("TButton", background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], focuscolor=p["surface"],
                            padding=(10, 5))
            style.map("TButton",
                      background=[("active", p["trough"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Accent.TButton", background=p["primary"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Accent.TButton",
                      background=[("active", p["primary_hi"]),
                                  ("disabled", p["border"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Toggle.TButton", background=p["surface"],
                            foreground=p["text"], padding=(8, 4))
            for name in ("TEntry", "TSpinbox"):
                style.configure(name, fieldbackground=p["entry"], foreground=p["text"],
                                insertcolor=p["text"], bordercolor=p["border"])
            style.configure("TCombobox", fieldbackground=p["entry"],
                            foreground=p["text"], background=p["surface"],
                            arrowcolor=p["text"])
            style.map("TCombobox",
                      fieldbackground=[("readonly", p["entry"])],
                      foreground=[("readonly", p["text"])])
            style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
            style.map("TRadiobutton", background=[("active", p["bg"])])
            style.configure("TLabelframe", background=p["bg"], foreground=p["text"],
                            bordercolor=p["border"])
            style.configure("TLabelframe.Label", background=p["bg"],
                            foreground=p["muted"])
            style.configure("Treeview", background=p["surface"],
                            fieldbackground=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], rowheight=24)
            style.map("Treeview", background=[("selected", p["primary"])],
                      foreground=[("selected", p["sel_fg"])])
            style.configure("Sidebar.Treeview", background=p["surface"],
                            fieldbackground=p["surface"])
            style.configure("Treeview.Heading", background=p["surface"],
                            foreground=p["muted"], font=(FONT, 9, "bold"))
            style.configure("TScrollbar", background=p["surface"],
                            troughcolor=p["bg"], bordercolor=p["border"],
                            arrowcolor=p["text"])
            style.configure("TSeparator", background=p["border"])

            # manually re-colour raw tk widgets (Listbox / Text / Canvas)
            for widget, role in list(self._tracked):
                try:
                    if role == "text":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         insertbackground=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                    elif role == "canvas":
                        widget.configure(bg=p["surface"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"])
                except Exception:
                    pass
            # redraw the ping chart under the new palette
            if getattr(self, "_ping_canvas", None) is not None:
                self._draw_ping_chart()

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            guiconfig.set_theme(self.theme)
            self._apply_theme()
            self._theme_btn.configure(
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")

        # ---- menu
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
            viewm.add_command(label="Toggle dark mode", command=self.toggle_theme)
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=self._about)
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
            panel = self._current
            var = getattr(panel, "host_var", None) if panel is not None else None
            if var is not None:
                var.set(target)

        def _clear_recent(self):
            guiconfig.clear_recent()
            self._fill_recent_menu()

        def remember_target(self, target):
            if target and str(target).strip():
                guiconfig.add_recent(str(target).strip())
                self._fill_recent_menu()

        # ---- layout
        def _build_layout(self):
            top = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 8))
            top.pack(fill="x", side="top")
            ttk.Label(top, text="NetScope", style="Brand.TLabel").pack(side="left")
            ttk.Label(top, style="Status.TLabel",
                      text="  offline · open source · by QuickOpen").pack(side="left")
            self._theme_btn = ttk.Button(
                top, style="Toggle.TButton", command=self.toggle_theme,
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")
            self._theme_btn.pack(side="right")

            body = ttk.Frame(self, style="TFrame")
            body.pack(fill="both", expand=True)

            side = ttk.Frame(body, style="Sidebar.TFrame", width=210)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            self.nav = ttk.Treeview(side, show="tree", selectmode="browse",
                                    style="Sidebar.Treeview")
            self.nav.pack(fill="both", expand=True, padx=6, pady=6)
            self._nav_ids = {}
            for cat, tools in TOOL_TREE:
                cid = self.nav.insert("", "end", text=cat, open=True, tags=("cat",))
                for tid, label in tools:
                    iid = self.nav.insert(cid, "end", text="   " + label)
                    self._nav_ids[iid] = tid
            self.nav.tag_configure("cat", font=(FONT, 10, "bold"))
            self.nav.bind("<<TreeviewSelect>>", self._on_nav_select)

            main = ttk.Frame(body, style="TFrame", padding=(16, 12))
            main.pack(side="left", fill="both", expand=True)

            head = ttk.Frame(main, style="TFrame")
            head.pack(fill="x")
            self.title_lbl = ttk.Label(head, text="Welcome", style="Header.TLabel")
            self.title_lbl.pack(anchor="w")
            self.desc_lbl = ttk.Label(head, text="", style="Sub.TLabel",
                                      wraplength=760, justify="left")
            self.desc_lbl.pack(anchor="w", pady=(2, 8))
            ttk.Separator(main).pack(fill="x")

            self.container = ttk.Frame(main, style="TFrame")
            self.container.pack(fill="both", expand=True, pady=(10, 8))

            bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 6))
            bar.pack(fill="x", side="bottom")
            self.status_lbl = ttk.Label(bar, text="Ready", style="Status.TLabel",
                                        width=16, anchor="w")
            self.status_lbl.pack(side="left")
            self.result_lbl = ttk.Label(bar, text="", style="Status.TLabel",
                                        anchor="w", wraplength=760, justify="left")
            self.result_lbl.pack(side="left", fill="x", expand=True, padx=8)

        def _select_first_tool(self):
            for iid in self._nav_ids:
                self.nav.selection_set(iid)
                self.nav.see(iid)
                break

        def _on_nav_select(self, _e=None):
            sel = self.nav.selection()
            if not sel:
                return
            tid = self._nav_ids.get(sel[0])
            if not tid:
                return  # a category row
            self._show_tool(tid)

        def _show_tool(self, tool_id):
            # stop any live ping when leaving the panel
            self._ping_stop.set()
            if self._current is not None:
                self._current.pack_forget()
            panel = self._panels.get(tool_id)
            if panel is None:
                panel = ttk.Frame(self.container, style="TFrame")
                builder = getattr(self, "_panel_" + tool_id, None)
                if builder:
                    builder(panel)
                else:
                    ttk.Label(panel, text="Not implemented.").pack()
                self._panels[tool_id] = panel
                self._apply_theme()
            panel.pack(fill="both", expand=True)
            self._current = panel
            self.title_lbl.configure(text=self._tool_label(tool_id))
            self.desc_lbl.configure(text=TOOL_DESCRIPTIONS.get(tool_id, ""))
            self._clear_result()

        def _tool_label(self, tool_id):
            for _cat, tools in TOOL_TREE:
                for tid, label in tools:
                    if tid == tool_id:
                        return label
            return tool_id

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown inline (NetScopeError message, or a generic note),
            never as a traceback.  Refuses a second op while one is in flight.
            """
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._set_status(busy, kind="working")
            self._clear_result(keep_status=True)

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
                    self._set_status("error", kind="err")
                    self._show_error(err)
                    return
                self._set_status("done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- result bar helpers
        def _set_status(self, text, kind="idle"):
            p = self._pal()
            color = {"working": p["primary"], "ok": p["ok"], "err": p["err"]}.get(
                kind, p["muted"])
            self.status_lbl.configure(text=text, foreground=color)

        def _clear_result(self, keep_status=False):
            self.result_lbl.configure(text="")
            if not keep_status:
                self._set_status("Ready")

        def _show_error(self, message):
            self.result_lbl.configure(text="✕ " + message,
                                      foreground=self._pal()["err"])

        def report_success(self, message):
            self.result_lbl.configure(text="✓ " + message,
                                      foreground=self._pal()["ok"])
            self._set_status("done", kind="ok")

        # ---- shared widgets -------------------------------------------------
        def _host_row(self, parent, panel, label="Host / IP", default=""):
            """A labelled entry bound to ``panel.host_var`` (used by Recent)."""
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, width=14, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            ent = ttk.Entry(row, textvariable=var)
            ent.pack(side="left", fill="x", expand=True)
            panel.host_var = var
            return var

        def _make_output(self, parent, height=16):
            """A read-only monospaced Text area with a scrollbar (tracked)."""
            body = ttk.Frame(parent, style="TFrame")
            body.pack(fill="both", expand=True, pady=(8, 0))
            txt = tk.Text(body, wrap="none", height=height, font=(MONO, 10),
                          borderwidth=0)
            sb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
            xb = ttk.Scrollbar(parent, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=sb.set, xscrollcommand=xb.set)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True)
            xb.pack(fill="x")
            self.track(txt, "text")
            return txt

        def _set_text(self, txt, content):
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", content)
            txt.configure(state="disabled")

        # =====================================================================
        # PANELS
        # =====================================================================

        # ---------- Ping (with live RTT chart) ----------
        def _panel_ping(self, parent):
            host = self._host_row(parent, parent, default="1.1.1.1")
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Count", width=14, anchor="w").pack(side="left")
            count = tk.StringVar(value="10")
            ttk.Spinbox(row, from_=1, to=100, textvariable=count, width=6).pack(side="left")
            ttk.Label(row, text="Method").pack(side="left", padx=(16, 4))
            method = tk.StringVar(value="auto")
            ttk.Combobox(row, textvariable=method, state="readonly", width=8,
                         values=["auto", "os", "tcp"]).pack(side="left")
            ttk.Label(row, text="TCP port").pack(side="left", padx=(16, 4))
            port = tk.StringVar(value="443")
            ttk.Spinbox(row, from_=1, to=65535, textvariable=port, width=7).pack(side="left")

            btns = ttk.Frame(parent, style="TFrame")
            btns.pack(fill="x", pady=6)
            run = ttk.Button(btns, text="Start ping", style="Accent.TButton")
            run.pack(side="left")
            stop = ttk.Button(btns, text="Stop", command=lambda: self._ping_stop.set())
            stop.pack(side="left", padx=6)

            self._ping_canvas = tk.Canvas(parent, height=220, borderwidth=0,
                                          highlightthickness=1)
            self._ping_canvas.pack(fill="both", expand=True, pady=(8, 0))
            self.track(self._ping_canvas, "canvas")
            self._ping_canvas.bind("<Configure>", lambda e: self._draw_ping_chart())

            def go():
                h = host.get().strip()
                if not h:
                    self._show_error("Enter a host or IP to ping.")
                    return
                try:
                    n = max(1, int(count.get()))
                    pr = int(port.get())
                except ValueError:
                    self._show_error("Count and port must be whole numbers.")
                    return
                self.remember_target(h)
                self._ping_rtts = []
                self._draw_ping_chart()
                self._start_ping(h, n, method.get(), pr, run)

            run.configure(command=go)

        def _start_ping(self, host, count, method, port, button):
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            self._ping_stop.clear()
            try:
                button.state(["disabled"])
            except Exception:
                pass
            self._set_status("pinging…", kind="working")
            self._clear_result(keep_status=True)
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
                        self.after(0, lambda e=str(ex): self._show_error(e))
                        break
                    except Exception as ex:
                        self.after(0, lambda e=str(ex):
                                   self._show_error(f"Unexpected error: {e}"))
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
                self._set_status("done", kind="ok")
                if self._ping_rtts:
                    avg = sum(self._ping_rtts) / len(self._ping_rtts)
                    self.report_success(
                        f"{sent['recv']}/{sent['n']} replies, {loss:.0f}% loss, "
                        f"avg {avg:.2f} ms "
                        f"(min {min(self._ping_rtts):.2f} / "
                        f"max {max(self._ping_rtts):.2f})")
                elif sent["n"]:
                    self._show_error(f"No replies from {host} "
                                     f"({sent['n']} attempts, 100% loss).")

            threading.Thread(target=worker, daemon=True).start()

        def _ping_tick(self, rtt, sent):
            if rtt is not None:
                self._ping_rtts.append(rtt)
            self._set_status(f"pinging… {sent['recv']}/{sent['n']}", kind="working")
            self._draw_ping_chart()

        def _draw_ping_chart(self):
            cv = getattr(self, "_ping_canvas", None)
            if cv is None:
                return
            try:
                cv.delete("all")
            except Exception:
                return
            p = self._pal()
            w = cv.winfo_width() or 600
            h = cv.winfo_height() or 220
            pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 24
            x0, y0 = pad_l, pad_t
            x1, y1 = w - pad_r, h - pad_b
            # axes
            cv.create_line(x0, y1, x1, y1, fill=p["border"])
            cv.create_line(x0, y0, x0, y1, fill=p["border"])
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
                cv.create_line(x0, yy, x1, yy, fill=p["grid"])
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
                cv.create_line(*flat, fill=p["chart"], width=2, smooth=False)
            for xx, yy in pts:
                cv.create_oval(xx - 3, yy - 3, xx + 3, yy + 3,
                               fill=p["chart"], outline=p["surface"])
            cv.create_text(x1, y0, anchor="ne",
                           text=f"last {data[-1]:.2f} ms  ·  avg "
                                f"{sum(data) / len(data):.2f} ms",
                           fill=p["muted"], font=(FONT, 9))

        # ---------- Traceroute ----------
        def _panel_trace(self, parent):
            host = self._host_row(parent, parent, default="quickopen.ai")
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Max hops", width=14, anchor="w").pack(side="left")
            hops = tk.StringVar(value="30")
            ttk.Spinbox(row, from_=1, to=64, textvariable=hops, width=6).pack(side="left")
            run = ttk.Button(parent, text="Trace route", style="Accent.TButton")
            run.pack(anchor="w", pady=6)
            out = self._make_output(parent)

            def go():
                h = host.get().strip()
                if not h:
                    self._show_error("Enter a host or IP.")
                    return
                try:
                    mh = int(hops.get())
                except ValueError:
                    self._show_error("Max hops must be a whole number.")
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
                    self.report_success(f"Traced {len(hop_list)} hop(s) to {h}.")

                self._bg(lambda: traceroute(h, max_hops=mh), ok, button=run)

            run.configure(command=go)

        # ---------- Port scan ----------
        def _panel_scan(self, parent):
            host = self._host_row(parent, parent, default="127.0.0.1")
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Ports", width=14, anchor="w").pack(side="left")
            ports = tk.StringVar(value="common")
            ttk.Entry(row, textvariable=ports).pack(side="left", fill="x", expand=True)
            ttk.Label(parent, style="Muted.TLabel",
                      text="Use 'common' for the built-in preset, or a list like "
                           "22,80,443,8000-8010.").pack(anchor="w")
            run = ttk.Button(parent, text="Scan ports", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            body = ttk.Frame(parent, style="TFrame")
            body.pack(fill="both", expand=True, pady=(8, 0))
            cols = ("port", "state", "service")
            tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
            for c, w, anc in (("port", 90, "e"), ("state", 90, "center"),
                              ("service", 200, "w")):
                tree.heading(c, text=c.title())
                tree.column(c, width=w, anchor=anc)
            sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)

            def go():
                h = host.get().strip()
                if not h:
                    self._show_error("Enter a host or IP.")
                    return
                try:
                    port_list = parse_ports(ports.get())
                except NetScopeError as ex:
                    self._show_error(str(ex))
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
                    self.report_success(
                        f"Scanned {len(results)} port(s) on {h}; "
                        f"{len(open_ports)} open.")

                self._bg(lambda: scan_ports(h, port_list, timeout=1.0), ok,
                         button=run)

            run.configure(command=go)

        # ---------- DNS lookup ----------
        def _panel_dns(self, parent):
            name = self._host_row(parent, parent, "Name", default="quickopen.ai")
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Type", width=14, anchor="w").pack(side="left")
            rtype = tk.StringVar(value="A")
            ttk.Combobox(row, textvariable=rtype, width=10, state="readonly",
                         values=COMMON_RECORD_TYPES).pack(side="left")
            run = ttk.Button(parent, text="Resolve", style="Accent.TButton")
            run.pack(anchor="w", pady=6)
            out = self._make_output(parent)

            def go():
                n = name.get().strip()
                if not n:
                    self._show_error("Enter a name to resolve.")
                    return
                self.remember_target(n)

                def ok(answers):
                    self._set_text(out, "\n".join(answers) or "(no answers)")
                    self.report_success(
                        f"{n} {rtype.get()} → {len(answers)} answer(s).")

                self._bg(lambda: resolve(n, rtype.get()), ok, button=run)

            run.configure(command=go)

        # ---------- All records ----------
        def _panel_records(self, parent):
            name = self._host_row(parent, parent, "Name", default="quickopen.ai")
            run = ttk.Button(parent, text="Look up all records",
                             style="Accent.TButton")
            run.pack(anchor="w", pady=6)
            out = self._make_output(parent)

            def go():
                n = name.get().strip()
                if not n:
                    self._show_error("Enter a name.")
                    return
                self.remember_target(n)

                def ok(recs):
                    if not recs:
                        self._set_text(out, "(no records found)")
                        self.report_success(f"No records for {n}.")
                        return
                    lines = []
                    for rtype, answers in recs.items():
                        for ans in answers:
                            lines.append(f"{rtype:<6} {ans}")
                    self._set_text(out, "\n".join(lines))
                    self.report_success(
                        f"{n}: {sum(len(v) for v in recs.values())} record(s) "
                        f"across {len(recs)} type(s).")

                self._bg(lambda: all_records(n), ok, button=run)

            run.configure(command=go)

        # ---------- Reverse DNS ----------
        def _panel_reverse(self, parent):
            ip = self._host_row(parent, parent, "IP address", default="1.1.1.1")
            run = ttk.Button(parent, text="Reverse lookup", style="Accent.TButton")
            run.pack(anchor="w", pady=6)
            out = self._make_output(parent, height=8)

            def go():
                v = ip.get().strip()
                if not v:
                    self._show_error("Enter an IP address.")
                    return
                self.remember_target(v)

                def ok(names):
                    self._set_text(out, "\n".join(names) or "(no PTR record)")
                    self.report_success(f"{v} → {len(names)} name(s).")

                self._bg(lambda: reverse(v), ok, button=run)

            run.configure(command=go)

        # ---------- Resolver benchmark ----------
        def _panel_benchmark(self, parent):
            name = self._host_row(parent, parent, "Name", default="example.com")
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="Resolvers", width=14, anchor="w").pack(side="left")
            resolvers = tk.StringVar(value="1.1.1.1, 8.8.8.8, 9.9.9.9")
            ttk.Entry(row, textvariable=resolvers).pack(side="left", fill="x", expand=True)
            run = ttk.Button(parent, text="Benchmark", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            body = ttk.Frame(parent, style="TFrame")
            body.pack(fill="both", expand=True, pady=(8, 0))
            cols = ("resolver", "ms", "result")
            tree = ttk.Treeview(body, columns=cols, show="headings", height=10)
            for c, w, anc in (("resolver", 160, "w"), ("ms", 100, "e"),
                              ("result", 260, "w")):
                tree.heading(c, text=c.title())
                tree.column(c, width=w, anchor=anc)
            sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)

            def go():
                n = name.get().strip() or "example.com"
                ips = [r.strip() for r in resolvers.get().replace(";", ",").split(",")
                       if r.strip()]
                if not ips:
                    self._show_error("Enter at least one resolver IP.")
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
                        self.report_success(
                            f"Fastest: {best['resolver']} at {best['ms']:.2f} ms.")
                    else:
                        self._show_error("No resolver answered.")

                self._bg(lambda: dns_benchmark(ips, name=n), ok, button=run)

            run.configure(command=go)

        # ---------- WHOIS ----------
        def _panel_whois(self, parent):
            q = self._host_row(parent, parent, "Domain / IP", default="quickopen.ai")
            follow = tk.BooleanVar(value=True)
            ttk.Checkbutton(parent, text="Follow registry referral",
                            variable=follow).pack(anchor="w")
            run = ttk.Button(parent, text="WHOIS lookup", style="Accent.TButton")
            run.pack(anchor="w", pady=6)
            out = self._make_output(parent)

            def go():
                v = q.get().strip()
                if not v:
                    self._show_error("Enter a domain or IP.")
                    return
                self.remember_target(v)
                self._set_text(out, "Querying WHOIS…")

                def ok(text):
                    self._set_text(out, text.rstrip() or "(empty response)")
                    self.report_success(f"WHOIS for {v} retrieved.")

                self._bg(lambda: whois(v, follow=follow.get()), ok, button=run)

            run.configure(command=go)

        # ---------- Subnet calculator (instant, no thread) ----------
        def _panel_subnet(self, parent):
            row = ttk.Frame(parent, style="TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text="CIDR", width=14, anchor="w").pack(side="left")
            cidr = tk.StringVar(value="192.0.2.0/24")
            ent = ttk.Entry(row, textvariable=cidr)
            ent.pack(side="left", fill="x", expand=True)
            ttk.Label(parent, style="Muted.TLabel",
                      text="IPv4 or IPv6, e.g. 198.51.100.0/8, 192.0.2.10/24, "
                           "2001:db8::/48. Updates as you type.").pack(anchor="w")
            out = self._make_output(parent, height=14)

            def recompute(*_):
                text = cidr.get().strip()
                if not text:
                    self._set_text(out, "")
                    self._clear_result()
                    return
                try:
                    info = subnet_info(text)
                except NetScopeError as ex:
                    self._set_text(out, "")
                    self._show_error(str(ex))
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
                self.report_success(
                    f"{info['cidr']} — {info['num_usable_hosts']} usable host(s).")

            cidr.trace_add("write", recompute)
            self.after(60, recompute)

        # ---------- LAN discovery ----------
        def _panel_discover(self, parent):
            mode = tk.StringVar(value="arp")
            box = ttk.Labelframe(parent, text="Method", padding=8)
            box.pack(fill="x", pady=6)
            ttk.Radiobutton(box, text="Read system ARP table (instant)",
                            value="arp", variable=mode).pack(anchor="w")
            r2 = ttk.Frame(box, style="TFrame")
            r2.pack(fill="x")
            ttk.Radiobutton(r2, text="TCP-connect sweep of", value="sweep",
                            variable=mode).pack(side="left")
            net = tk.StringVar()
            ttk.Entry(r2, textvariable=net, width=22).pack(side="left", padx=6)
            ttk.Label(r2, style="Muted.TLabel",
                      text="(blank = local /24)").pack(side="left")
            run = ttk.Button(parent, text="Discover hosts", style="Accent.TButton")
            run.pack(anchor="w", pady=6)

            body = ttk.Frame(parent, style="TFrame")
            body.pack(fill="both", expand=True, pady=(8, 0))
            cols = ("ip", "detail")
            tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
            tree.heading("ip", text="IP address")
            tree.heading("detail", text="MAC / open ports")
            tree.column("ip", width=160, anchor="w")
            tree.column("detail", width=320, anchor="w")
            sb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)

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
                            tree.insert("", "end", values=("—", "no hosts responded"))
                        self.report_success(f"Sweep found {len(rows)} live host(s).")

                    self._bg(work, ok, button=run, busy="Sweeping…")
                else:
                    def ok(rows):
                        for r in rows:
                            detail = r["mac"] or "(incomplete)"
                            if r["host"]:
                                detail += f"  {r['host']}"
                            tree.insert("", "end", values=(r["ip"], detail))
                        if not rows:
                            tree.insert("", "end", values=("—", "ARP table empty"))
                        self.report_success(f"ARP table: {len(rows)} entr(y/ies).")

                    self._bg(arp_table, ok, button=run)

            run.configure(command=go)

        # ---- About
        def _about(self):
            win = tk.Toplevel(self)
            win.title("About NetScope")
            win.configure(bg=self._pal()["bg"])
            win.resizable(False, False)
            frm = ttk.Frame(win, style="TFrame", padding=18)
            frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="NetScope", style="Header.TLabel").pack(anchor="w")
            ttk.Label(frm, text=f"Version {APP_VERSION}",
                      style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            ttk.Label(frm, style="TLabel", justify="left", wraplength=380,
                      text="A fast, fully-offline network toolkit — ping, "
                           "traceroute, port scan, DNS, WHOIS, reverse-DNS, a "
                           "subnet calculator and LAN discovery.\n\n"
                           "100% AI-built, open source, published on QuickOpen.\n"
                           "Nothing is ever uploaded anywhere.").pack(anchor="w")
            ttk.Label(frm, style="Sub.TLabel", justify="left", wraplength=380,
                      text="Licensed under Apache-2.0. Built on the Python "
                           "standard library plus dnspython.").pack(
                anchor="w", pady=(8, 4))
            link = ttk.Label(frm, text="Project page: quickopen.ai",
                             style="Ok.TLabel", cursor="hand2")
            link.pack(anchor="w", pady=(4, 10))
            link.bind("<Button-1>", lambda e: open_with_default_app(PROJECT_URL))
            ttk.Button(frm, text="Close", command=win.destroy).pack(anchor="e")
            win.transient(self)
            win.grab_set()

        # ---- shutdown
        def _on_close(self):
            self._ping_stop.set()
            self.destroy()

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server), it prints a friendly note and returns 0
    instead of raising.
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
