"""Record shape: one verdict per checkable claim, JSON round trip, line spans."""

from datetime import datetime, timezone

import pytest
from claimcheck.constants import __version__
from claimcheck.models import Claim, ClaimKind, Evidence, Label, Report, Verdict
from pydantic import ValidationError


def _claim(claim_id: str = "c001", *, checkable: bool = True) -> Claim:
    return Claim(
        id=claim_id,
        text="The tool writes a JSON report.",
        kind=ClaimKind.feature,
        checkable=checkable,
        skip_reason=None if checkable else "marketing",
        readme_path="README.md",
        readme_line=4,
        readme_line_end=4,
        quote="writes a JSON report",
    )


def _report(claims: list[Claim], verdicts: list[Verdict]) -> Report:
    return Report(
        tool_version=__version__,
        mode="test",
        project="sample",
        readme_path="README.md",
        generated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        claims=claims,
        verdicts=verdicts,
        limitations=[],
    )


def test_report_round_trip_keeps_the_label_and_evidence_location() -> None:
    evidence = Evidence(
        path="src/app.py",
        line=12,
        line_end=14,
        quote="return report",
        note="the writer",
    )
    claim = _claim()
    report = _report(
        [claim],
        [
            Verdict(
                claim_id="c001",
                label=Label.supported,
                evidence=[evidence],
                rationale="The function returns the report.",
            )
        ],
    )
    restored = Report.model_validate_json(report.model_dump_json())
    assert restored.verdicts[0].label is Label.supported
    assert restored.verdicts[0].evidence[0].location() == "src/app.py:12-14"
    assert restored.generated_at.tzinfo is not None


def test_unverifiable_verdict_may_cite_no_evidence() -> None:
    report = _report(
        [_claim()],
        [
            Verdict(
                claim_id="c001",
                label=Label.unverifiable,
                rationale="No evidence was collected.",
                provisional=True,
            )
        ],
    )
    assert report.verdict_for("c001").evidence == []


def test_skipped_claims_have_no_verdict_and_checkable_claims_need_one() -> None:
    claims = [_claim("c001"), _claim("c002", checkable=False)]
    report = _report(
        claims,
        [Verdict(claim_id="c001", label=Label.not_found, rationale="Nothing matched.")],
    )
    assert [verdict.claim_id for verdict in report.verdicts] == ["c001"]


def test_two_verdicts_for_one_claim_are_rejected() -> None:
    claim = _claim()
    verdict = Verdict(claim_id="c001", label=Label.not_found, rationale="Missing.")
    with pytest.raises(ValidationError):
        _report([claim], [verdict, verdict])


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Report(
            tool_version=__version__,
            mode="test",
            project="sample",
            readme_path="README.md",
            generated_at=datetime(2026, 11, 13),
            claims=[],
            verdicts=[],
        )


def test_evidence_line_span_must_run_forward() -> None:
    with pytest.raises(ValidationError):
        Evidence(path="a.py", line=8, line_end=3, quote="x")
