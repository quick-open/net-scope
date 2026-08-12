r"""Tiny JSON-backed config for the NetScope GUI.

Stores the chosen theme ("light"/"dark"), a short history of recent targets, and
a small custom DNS-resolver list -- and never raises.  On Windows the file lives
at ``%LOCALAPPDATA%\NetScope\config.json``; elsewhere it falls back to
``~/.netscope/config.json``.  Every function is defensive: a corrupt or
unreadable config must never stop the app from starting.
"""

from __future__ import annotations

import json
import os

APP_DIRNAME = "NetScope"
CONFIG_NAME = "config.json"
MAX_RECENT = 12
VALID_THEMES = ("light", "dark")
DEFAULT_RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]


def config_dir():
    r"""Directory that holds the config file (created on demand).

    ``%LOCALAPPDATA%\NetScope`` on Windows, ``~/.netscope`` otherwise.
    """
    local = os.environ.get("LOCALAPPDATA")
    if local and os.name == "nt":
        return os.path.join(local, APP_DIRNAME)
    return os.path.join(os.path.expanduser("~"), "." + APP_DIRNAME.lower())


def config_path():
    return os.path.join(config_dir(), CONFIG_NAME)


def _defaults():
    return {"theme": "light", "recent": [], "resolvers": list(DEFAULT_RESOLVERS)}


def load():
    """Return the config dict, always with the expected keys present."""
    cfg = _defaults()
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            theme = data.get("theme")
            if theme in VALID_THEMES:
                cfg["theme"] = theme
            recent = data.get("recent")
            if isinstance(recent, list):
                cfg["recent"] = [p for p in recent if isinstance(p, str)][:MAX_RECENT]
            resolvers = data.get("resolvers")
            if isinstance(resolvers, list):
                clean = [r for r in resolvers if isinstance(r, str) and r.strip()]
                if clean:
                    cfg["resolvers"] = clean
    except Exception:
        pass  # missing/corrupt -> defaults; never fatal
    return cfg


def save(cfg):
    """Persist *cfg* (best-effort; failures are swallowed)."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        clean = {
            "theme": cfg.get("theme") if cfg.get("theme") in VALID_THEMES else "light",
            "recent": [p for p in cfg.get("recent", []) if isinstance(p, str)][:MAX_RECENT],
            "resolvers": [r for r in cfg.get("resolvers", DEFAULT_RESOLVERS)
                          if isinstance(r, str) and r.strip()] or list(DEFAULT_RESOLVERS),
        }
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=2)
        os.replace(tmp, config_path())
    except Exception:
        pass


def get_theme():
    return load().get("theme", "light")


def set_theme(theme):
    if theme not in VALID_THEMES:
        return
    cfg = load()
    cfg["theme"] = theme
    save(cfg)


def get_recent():
    return load().get("recent", [])


def add_recent(target):
    """Push *target* (a host/IP/CIDR string) to the front of the recent list."""
    if not target or not str(target).strip():
        return
    target = str(target).strip()
    cfg = load()
    recent = [p for p in cfg.get("recent", []) if p != target]
    recent.insert(0, target)
    cfg["recent"] = recent[:MAX_RECENT]
    save(cfg)


def clear_recent():
    cfg = load()
    cfg["recent"] = []
    save(cfg)


def get_resolvers():
    return load().get("resolvers", list(DEFAULT_RESOLVERS))


def set_resolvers(resolvers):
    cfg = load()
    cfg["resolvers"] = [r for r in resolvers if isinstance(r, str) and r.strip()]
    save(cfg)
