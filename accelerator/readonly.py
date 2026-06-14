"""Read-only enforcement.

Honest accounting: of the five defence-in-depth layers in the architecture, TWO are
actively enforced on the live code path, the SELECT-only SQL guard and the read-only
tool-call guard (the shape of the Claude Agent SDK PreToolUse hook). A third, the
egress allowlist policy below, is implemented and unit-tested as a decision function
but is NOT yet on a live path: the only connector today is file-based (no egress), so
nothing routes through it until the first live-HTTP connector exists. It gates client
source egress (GET-only, allowlisted hosts), not the engine's own model API call. The
remaining two (client read-only OAuth scopes, which need a live OAuth provider, and
per-engagement network isolation, which needs infra) are explicit stubs that raise
rather than pretend. Counting an unbuilt layer as "done" would be the dishonest move.
"""
from __future__ import annotations

import re

_WRITE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|PRAGMA\s+\w+\s*=)",
                        re.IGNORECASE)
_READ_SQL = re.compile(r"^\s*(SELECT|WITH|EXPLAIN|PRAGMA\s+\w+\s*\(|VALUES)", re.IGNORECASE)

_READ_HTTP = {"GET", "HEAD", "OPTIONS"}


class ReadOnlyViolation(Exception):
    pass


def assert_select_only(sql: str) -> None:
    """Raise ReadOnlyViolation unless sql is a read. Enforced layer 1."""
    if _WRITE_SQL.match(sql or "") or not _READ_SQL.match(sql or ""):
        raise ReadOnlyViolation(f"non-read SQL refused: {sql[:60]!r}")


def read_only_tool_guard(tool_name: str, args: dict) -> tuple[str, str]:
    """Mirror of the Agent SDK PreToolUse hook: returns (decision, reason) where
    decision is 'allow' or 'deny'. Denies any write HTTP verb, any non-read SQL,
    and any filesystem-mutating tool. Enforced layer 2. Default deny on unknown."""
    name = (tool_name or "").lower()
    if name in {"write", "edit", "multiedit", "notebookedit", "bash"}:
        return "deny", f"{tool_name} can mutate; read-only engine"
    if "sql" in name or name in {"query", "warehouse_query"}:
        sql = str(args.get("sql", args.get("query", "")))
        try:
            assert_select_only(sql)
            return "allow", "select-only"
        except ReadOnlyViolation as e:
            return "deny", str(e)
    if name in {"http", "fetch", "request", "curl"}:
        verb = str(args.get("method", "GET")).upper()
        return ("allow", verb) if verb in _READ_HTTP else ("deny", f"write verb {verb}")
    if name in {"read", "get_entity", "search_index", "list_events"}:
        return "allow", "read tool"
    return "deny", f"unknown tool {tool_name}, default-deny"


# ---- explicit stubs, layers gated on live infrastructure (iteration 2+) -------

def require_readonly_oauth_scope(connector: str, granted_scopes: list[str]) -> None:
    raise NotImplementedError(
        "STUB: read-only OAuth scope verification needs a live OAuth provider per "
        "connector (iteration 2). Until then, read-only at the source is NOT enforced "
        "by EGNTA, only documented in the per-engagement scope manifest.")


# the only host the engine itself needs to reach: the model API. A client engagement
# adds its read-only source hosts to the allowlist at configuration time.
_DEFAULT_EGRESS_ALLOWLIST = frozenset({"api.anthropic.com"})


def egress_allowlist_check(host: str, method: str,
                           allowlist: frozenset = _DEFAULT_EGRESS_ALLOWLIST) -> None:
    """Read-only client-source egress policy: raise ReadOnlyViolation on a write HTTP
    verb or a host outside the allowlist. This is the decision function (layer 3),
    implemented and tested; it becomes active when a live-HTTP connector routes its
    egress through it, and a forward proxy at deploy time makes it network-level. It
    gates client source reads, not the engine's own POST to the model API."""
    if (method or "").upper() not in _READ_HTTP:
        raise ReadOnlyViolation(f"egress write verb refused: {method!r}")
    if host not in allowlist:
        raise ReadOnlyViolation(f"egress host not allowlisted: {host!r}")
