"""Markdown and text renderers, including the milestone-1 placeholder report."""

import json
from datetime import datetime, timezone
from pathlib import Path

from claimcheck.constants import STUB_RATIONALE, __version__
from claimcheck.extract import extract_claims
from claimcheck.format import format_extraction, render_json, render_markdown
from claimcheck.llm import ReplayClient
from claimcheck.models import Claim, ClaimKind, Evidence, Label, Report, Verdict
from claimcheck.readme import ReadmeDocument
from claimcheck.scan import build_stub_report


def _document() -> ReadmeDocument:
    return ReadmeDocument(
        path=Path("examples/sample_readme.md"),
        display_path="examples/sample_readme.md",
        lines=(
            "# Notes",
            "",
            "Search returns results in under 50 ms on the sample corpus.",
        ),
    )


def test_stub_scan_labels_every_claim_unverifiable_and_says_so() -> None:
    payload = json.dumps(
        {
            "claims": [
                {
                    "text": "Search returns results in under 50 ms on the sample corpus.",
                    "kind": "benchmark_number",
                    "quote": "Search returns results in under 50 ms on the sample corpus.",
                    "line": 3,
                    "checkable": True,
                    "skip_reason": None,
                }
            ]
        }
    )
    report = build_stub_report(
        _document(),
        ReplayClient([payload]),
        generated_at=datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
    )
    assert report.mode == "milestone-1-stub"
    assert [verdict.label for verdict in report.verdicts] == [Label.unverifiable]
    assert report.verdicts[0].provisional is True
    assert report.verdicts[0].evidence == []
    assert report.verdicts[0].rationale == STUB_RATIONALE
    markdown = render_markdown(report)
    assert markdown.index("## Limitations") < markdown.index("## Verdicts")
    assert "not a judgment" in markdown
    assert "unverifiable (provisional)" in markdown
    assert "Evidence: none" in markdown
    restored = Report.model_validate_json(render_json(report))
    assert restored.verdicts[0].label is Label.unverifiable


def test_renderer_links_evidence_file_and_line() -> None:
    claim = Claim(
        id="c001",
        text="The function writes the file.",
        kind=ClaimKind.feature,
        checkable=True,
        readme_path="README.md",
        readme_line=2,
        readme_line_end=2,
        quote="writes the file",
    )
    report = Report(
        tool_version=__version__,
        mode="manual",
        project="demo",
        readme_path="README.md",
        generated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        claims=[claim],
        verdicts=[
            Verdict(
                claim_id="c001",
                label=Label.contradicted,
                evidence=[
                    Evidence(path="src/writer.py", line=40, quote="raise NotImplementedError")
                ],
                rationale="The writer raises instead of writing.",
            )
        ],
        limitations=[],
    )
    markdown = render_markdown(report)
    assert "[`src/writer.py:40`](src/writer.py#L40)" in markdown
    assert "raise NotImplementedError" in markdown
    assert "contradicted" in markdown


def test_extraction_text_lists_skipped_statements() -> None:
    document = _document()
    payload = json.dumps(
        {
            "claims": [
                {
                    "text": "It is the best.",
                    "kind": "other",
                    "quote": "Search returns results in under 50 ms on the sample corpus.",
                    "line": 1,
                    "checkable": False,
                    "skip_reason": "not a checkable statement",
                }
            ]
        }
    )
    result = extract_claims(document, ReplayClient([payload]))
    text = format_extraction(result)
    assert "Skipped 1 not-checkable" in text
    assert "examples/sample_readme.md:3" in text
    assert "not a checkable statement" in text
