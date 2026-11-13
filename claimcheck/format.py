"""Text and Markdown renderers for extraction results and reports."""

from urllib.parse import quote

from claimcheck.models import ExtractionResult, Report


def format_extraction(result: ExtractionResult) -> str:
    """Human-readable extract output. The JSON form is the machine-readable one."""
    checkable = [claim for claim in result.claims if claim.checkable]
    skipped = [claim for claim in result.claims if not claim.checkable]
    lines = [
        f"Extracted {len(checkable)} checkable claim(s) from {result.readme_path}.",
        f"Skipped {len(skipped)} not-checkable statement(s).",
        f"Model attempts: {result.attempts}.",
    ]
    if result.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result.warnings)
    lines.append("")
    if not result.claims:
        lines.append("No claims were extracted.")
        return "\n".join(lines).rstrip() + "\n"
    for claim in result.claims:
        status = claim.kind.value if claim.checkable else "not checkable"
        span = _span(claim.readme_path, claim.readme_line, claim.readme_line_end)
        lines.append(f"[{claim.id}] {status}  {span}")
        lines.append(f"  {claim.text}")
        lines.append(f"  quote: {claim.quote}")
        if claim.skip_reason:
            lines.append(f"  reason: {claim.skip_reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(report: Report) -> str:
    """Render a report. Limitations are printed before any verdict."""
    lines = [
        "# ClaimCheck report",
        "",
        f"- Project: `{report.project}`",
        f"- README: `{report.readme_path}`",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Tool: claimcheck {report.tool_version}",
        f"- Mode: `{report.mode}`",
        "",
    ]
    if report.limitations:
        lines.append("## Limitations")
        lines.append("")
        lines.extend(f"- {item}" for item in report.limitations)
        lines.append("")
    if report.warnings:
        lines.append("## Extraction warnings")
        lines.append("")
        lines.extend(f"- {warning}" for warning in report.warnings)
        lines.append("")

    by_id = {verdict.claim_id: verdict for verdict in report.verdicts}
    checkable = [claim for claim in report.claims if claim.checkable]
    skipped = [claim for claim in report.claims if not claim.checkable]
    lines.append(f"## Verdicts ({len(checkable)})")
    lines.append("")
    if not checkable:
        lines.append("No checkable claims were extracted.")
        lines.append("")
    for claim in checkable:
        verdict = by_id[claim.id]
        provisional = " (provisional)" if verdict.provisional else ""
        lines.append(f"### {claim.id} — {verdict.label.value}{provisional}")
        lines.append("")
        lines.append(f"> {claim.text}")
        lines.append("")
        lines.append(f"- Kind: `{claim.kind.value}`")
        lines.append(
            "- README: "
            + _linked(_span(claim.readme_path, claim.readme_line, claim.readme_line_end))
        )
        lines.append(f"- Quote: {claim.quote}")
        if verdict.evidence:
            lines.append("- Evidence:")
            for item in verdict.evidence:
                lines.append(f"  - {_linked(item.location())}")
                lines.append(f"    > {item.quote}")
                if item.note:
                    lines.append(f"    - {item.note}")
        else:
            lines.append("- Evidence: none")
        lines.append(f"- Rationale: {verdict.rationale}")
        lines.append("")

    lines.append(f"## Not checked ({len(skipped)})")
    lines.append("")
    if not skipped:
        lines.append("Nothing was marked not checkable.")
        lines.append("")
    for claim in skipped:
        lines.append(
            f"### {claim.id} — skipped "
            + _linked(_span(claim.readme_path, claim.readme_line, claim.readme_line_end))
        )
        lines.append("")
        lines.append(f"> {claim.text}")
        lines.append("")
        lines.append(f"- Reason: {claim.skip_reason}")
        lines.append(f"- Quote: {claim.quote}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(report: Report) -> str:
    """Stable pretty JSON. Enums and timestamps are already plain values."""
    return report.model_dump_json(indent=2) + "\n"


def _span(path: str, start: int, end: int) -> str:
    if end != start:
        return f"{path}:{start}-{end}"
    return f"{path}:{start}"


def _linked(location: str) -> str:
    """Markdown link whose visible text is `path:line`. The target uses #Lline."""
    path, _, rest = location.partition(":")
    line = rest.split("-", 1)[0]
    safe_path = quote(path, safe="/")
    visible = location.replace("`", "'")
    return f"[`{visible}`]({safe_path}#L{line})"
