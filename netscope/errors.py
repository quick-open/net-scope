"""Error types for netscope."""


class NetScopeError(Exception):
    """Raised for any recoverable failure in a netscope operation.

    Every public function raises this (and only this) on an expected failure --
    a missing system tool, an unresolvable name, a bad CIDR, a refused socket --
    so callers (the CLI and the GUI) have a single exception type to catch and
    can show the message without ever leaking a raw traceback.
    """
