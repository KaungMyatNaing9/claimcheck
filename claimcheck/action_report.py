"""Job summary, pull-request comment, and diff highlights for the GitHub Action.

The action calls these functions after a normal scan. Nothing here talks to
GitHub except the comment client the caller passes in.
"""

import re
from collections import Counter
from dataclasses import dataclass

from claimcheck.models import Label, Report

COMMENT_MARKER = "<!-- claimcheck-report -->"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_COMMENT_LIMIT = 60_000


@dataclass(frozen=True)
class ClaimHighlight:
    """A claim whose README line or cited evidence intersects the pull request diff."""

    claim_id: str
    label: str
    text: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PullRequestDiff:
    """Changed files between two commits.

    A file mapped to None means the file changed and line hunks were not read.
    A file mapped to a tuple of ranges means those new-file line spans changed.
    """

    available: bool
    note: str
    files: dict[str, tuple[tuple[int, int], ...] | None]


def parse_name_status(text: str) -> dict[str, str]:
    """Parse `git diff --name-status` output into path -> status letter."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        if not path or status[:1] not in {"A", "M", "D", "R", "C", "T", "U"}:
            continue
        found[path.replace("\\", "/")] = status[:1]
    return found


def parse_hunks(diff_text: str) -> tuple[tuple[int, int], ...]:
    """New-file line spans from a unified diff. A pure deletion contributes no span."""
    spans: list[tuple[int, int]] = []
    for line in diff_text.splitlines():
        match = _HUNK.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count <= 0 or start <= 0:
            continue
        spans.append((start, start + count - 1))
    return tuple(spans)


def highlights_for(report: Report, diff: PullRequestDiff) -> list[ClaimHighlight]:
    """Claims to call out because this pull request touched their evidence or README line."""
    if not diff.available:
        return []
    found: list[ClaimHighlight] = []
    verdicts = {verdict.claim_id: verdict for verdict in report.verdicts}
    for claim in report.claims:
        if not claim.checkable:
            continue
        reasons: list[str] = []
        verdict = verdicts[claim.id]
        readme = _match_path(claim.readme_path, diff.files)
        if readme is not None and _line_touched(claim.readme_line, claim.readme_line_end, readme):
            reasons.append(f"README line {claim.readme_line} is in the diff")
        for item in verdict.evidence:
            spans = _match_path(item.path, diff.files)
            if spans is None:
                continue
            if _line_touched(item.line, item.line_end or item.line, spans):
                reasons.append(f"evidence `{item.path}` changed")
        if reasons:
            found.append(
                ClaimHighlight(
                    claim_id=claim.id,
                    label=verdict.label.value,
                    text=claim.text,
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )
    return found


def render_job_summary(
    report: Report, diff: PullRequestDiff, highlights: list[ClaimHighlight]
) -> str:
    """Markdown for the job summary. The full report follows the diff section."""
    counts = Counter(verdict.label.value for verdict in report.verdicts)
    lines = [
        "# ClaimCheck",
        "",
        _count_line(counts, len(report.verdicts)),
        "",
        "## Pull request diff",
        "",
        diff.note,
        "",
    ]
    if diff.available and highlights:
        lines.append("## Claims touched by this pull request")
        lines.append("")
        for item in highlights:
            why = "; ".join(item.reasons)
            lines.append(f"- `{item.claim_id}` **{item.label}** — {why}")
            lines.append(f"  > {item.text}")
        lines.append("")
    elif diff.available:
        lines.append(
            "No claim in this report has a README line or cited evidence line in the diff."
        )
        lines.append("")
    lines.append(render_report_body(report))
    return "\n".join(lines).rstrip() + "\n"


def render_comment(report: Report, diff: PullRequestDiff, highlights: list[ClaimHighlight]) -> str:
    """One pull-request comment. The marker is how a later run finds this comment."""
    body = COMMENT_MARKER + "\n\n" + render_job_summary(report, diff, highlights)
    if len(body) <= _COMMENT_LIMIT:
        return body
    note = (
        "\n\nThe full report is in the job summary. "
        "This comment was shortened to fit GitHub's comment size.\n"
    )
    kept = body[: _COMMENT_LIMIT - len(note)].rstrip() + note
    return kept


def fail_on_code(report: Report, fail_on: str) -> int:
    """Exit status after a successful scan. `none` does not fail the job."""
    if fail_on == "none":
        return 0
    if fail_on == "contradicted":
        if any(verdict.label is Label.contradicted for verdict in report.verdicts):
            return 1
        return 0
    raise ValueError(f"fail-on must be 'none' or 'contradicted', got {fail_on!r}")


def render_report_body(report: Report) -> str:
    """The same markdown `claimcheck scan` writes, imported lazily to keep this module small."""
    from claimcheck.format import render_markdown

    return render_markdown(report)


def _count_line(counts: Counter[str], total: int) -> str:
    parts = [f"{label.value} {counts[label.value]}" for label in Label]
    return f"{total} verdict(s): " + ", ".join(parts) + "."


def _match_path(
    cited: str, files: dict[str, tuple[tuple[int, int], ...] | None]
) -> tuple[tuple[int, int], ...] | None:
    """Return hunks for a cited path, or None when that path is not in the diff."""
    target = _norm(cited)
    for path, spans in files.items():
        if _norm(path) == target or target.endswith("/" + _norm(path)):
            return spans
    return None


def _line_touched(start: int, end: int, spans: tuple[tuple[int, int], ...] | None) -> bool:
    """None means the file changed and line hunks were not available, so the file counts."""
    if spans is None:
        return True
    for hunk_start, hunk_end in spans:
        if start <= hunk_end and hunk_start <= end:
            return True
    return False


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")
