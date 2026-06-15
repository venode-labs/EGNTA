"""Render a pain register as a plain-language report, the artefact a business owner
actually reads. Takes the graded findings and writes a prioritised markdown table
plus a per-finding remediation, ordered by the RICE-like score the engine computes.

The remediation lines are a fixed domain playbook keyed by defect kind, standard
trade remediations, not fabricated client specifics. The LLM synthesis layer writes
sharper, evidence-specific recommendations; this is the deterministic floor so a
report exists with no key and no network.
"""
from __future__ import annotations

from .model import Finding

# standard remediation per defect kind. Generic and honest: the playbook step, not a
# made-up client detail. The grounded synthesis tightens these against the evidence.
_PLAYBOOK = {
    "unbilled-completion": "Reconcile completed jobs against issued invoices weekly; gate job close on an invoice raised.",
    "rectification-stall": "Put every open defect on an ageing report; assign an owner and a due date at the point it is raised.",
    "compliance-overdue": "Drive routine servicing off the asset register's due dates, not memory; escalate anything past its AS 1851 interval.",
    "approval-gap": "Require a recorded quote approval or purchase order before a job is scheduled or invoiced.",
    "rework-loop": "Track first-time-fix rate per technician and job type; review the repeat-visit jobs for a root cause.",
    "dispatch-bottleneck": "Measure the slow stage as a queue; resource the dispatch step or change how jobs are released into it.",
    "segregation-of-duties": "Separate who quotes from who approves above a dollar threshold; the same person should not do both.",
    "cross-source-orphan": "Reconcile finance against the field-service system; every invoice should trace to a completed job.",
    "recording-error": "Fix the data entry at source; out-of-order timestamps corrupt every downstream timing metric.",
}

_SEVERITY_BAND = ((0.8, "Critical"), (0.6, "High"), (0.4, "Medium"))


def _band(severity: float) -> str:
    for floor, label in _SEVERITY_BAND:
        if severity >= floor:
            return label
    return "Low"


def _cell(s) -> str:
    """Neutralise a value before it goes into the report: escape the markdown pipe so a
    title cannot break the table, and prefix a leading spreadsheet-formula character so a
    hostile export value (=cmd, +, -, @) cannot execute if the report is opened in Excel."""
    out = str(s).replace("|", r"\|").replace("\n", " ").replace("\r", " ")
    return "'" + out if out[:1] in ("=", "+", "-", "@", "\t") else out


def render(findings: list[Finding], vertical: str = "trades") -> str:
    """A prioritised markdown pain register. Empty findings render an explicit
    'no material findings' line rather than a blank report."""
    ordered = sorted(findings, key=lambda f: f.score, reverse=True)
    lines = [f"# Discovery pain register, {vertical}", ""]
    if not ordered:
        lines.append("No material findings on the data reviewed.")
        return "\n".join(lines) + "\n"
    lines += [f"{len(ordered)} findings, ordered by impact (frequency x severity x fixability).", "",
              "| # | Priority | Finding | Score |", "|---|---|---|---|"]
    for i, f in enumerate(ordered, 1):
        lines.append(f"| {i} | {_band(f.severity)} | {_cell(f.title)} | {f.score} |")
    lines.append("")
    for i, f in enumerate(ordered, 1):
        rec = _PLAYBOOK.get(f.kind, "Review with the operator and agree a remediation.")
        lines += [f"### {i}. {_cell(f.title)}",
                  f"- Priority: {_band(f.severity)} (severity {f.severity}, frequency {f.frequency})",
                  f"- Evidence: `{f.evidence_fqn}`",
                  f"- Recommendation: {rec}", ""]
    return "\n".join(lines) + "\n"
