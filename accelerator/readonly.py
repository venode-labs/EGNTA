"""Read-only enforcement.

Honest accounting: of the five defence-in-depth layers in the architecture, TWO
are enforceable in code today and live here, the SELECT-only SQL guard and the
read-only tool-call guard (the shape of the Claude Agent SDK PreToolUse hook).
The other three (client read-only OAuth scopes, an egress proxy that blocks write
verbs, per-engagement network isolation) require live infrastructure and are
explicit stubs below, raising rather than pretending. Counting them as "done"
before they exist would be the dishonest move, so they raise NotImplementedError.
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
        "by Egenta, only documented in the per-engagement scope manifest.")


def egress_allowlist_check(host: str, method: str) -> None:
    raise NotImplementedError(
        "STUB: egress write-verb allowlist needs a real forward proxy (iteration 2). "
        "Until then, egress is NOT enforced by Egenta.")
