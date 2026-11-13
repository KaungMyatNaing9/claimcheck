"""End-to-end scan of the in-tree fixture, using the recorded model responses."""

import json
import subprocess
import sys
from pathlib import Path

from claimcheck.cli import main
from claimcheck.ground_truth import load_ground_truth
from claimcheck.models import Label, Report
from claimcheck.verdict_score import score_verdicts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "tiny_repo"
REPLAY = ROOT / "fixtures" / "tiny_repo_replay.json"
GOLD = ROOT / "eval" / "ground_truth" / "tiny_repo.json"


def test_scan_assigns_the_four_labels(tmp_path: Path) -> None:
    code = main(
        [
            "scan",
            str(FIXTURE),
            "--replay",
            str(REPLAY),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    report = Report.model_validate_json((tmp_path / "report.json").read_text(encoding="utf-8"))
    by_text = {
        claim.text: report.verdict_for(claim.id) for claim in report.claims if claim.checkable
    }
    assert (
        by_text["The index_notes function writes a SQLite database at notes.db."].label
        is Label.supported
    )
    assert (
        by_text["TinyLib detects contradictions in stored facts before saving them."].label
        is Label.contradicted
    )
    assert by_text["TinyLib exposes a GraphQL endpoint for queries."].label is Label.not_found
    assert by_text["Recall at 5 on the bundled sample is 90%."].label is Label.supported
    assert by_text["Sample accuracy is 99%."].label is Label.contradicted
    assert by_text["A Haiku rerank reaches 100% on the bundled sample."].label is Label.unverifiable
    contradicted = by_text["Sample accuracy is 99%."]
    assert contradicted.evidence[0].location() == "benchmarks/sample_results.json:3"
    assert any(claim.checkable is False for claim in report.claims)
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "[`benchmarks/sample_results.json:3`](benchmarks/sample_results.json#L3)" in markdown
    assert "second pass" in markdown

    score = score_verdicts(load_ground_truth(GOLD).cases, report)
    assert score.strict_total == 6
    assert score.strict_correct == 6
    assert score.coarse_total == 0
    assert all(row.issue_severity for row in score.rows)


def test_fixture_readme_hash_matches_the_ground_truth_file() -> None:
    import hashlib

    digest = hashlib.sha256((FIXTURE / "README.md").read_bytes()).hexdigest()
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    assert gold["readme_sha256"] == digest
    assert gold["commit"] == "local"


def test_score_verdicts_script_splits_coarse_rows(tmp_path: Path) -> None:
    """The MemPalace rows stay grouped by mapping_is_coarse. This does not scan MemPalace."""
    from datetime import datetime, timezone

    from claimcheck.models import Claim, ClaimKind, Report, Verdict

    gold = load_ground_truth(ROOT / "eval" / "ground_truth" / "mempalace_issue_27.json")
    claims = []
    verdicts = []
    for index, case in enumerate(gold.cases, start=1):
        claim_id = f"c{index:03d}"
        claims.append(
            Claim(
                id=claim_id,
                text=case.claim_text,
                kind=ClaimKind.other,
                checkable=True,
                readme_path="README.md",
                readme_line=case.readme_line,
                readme_line_end=case.readme_line_end,
                quote=case.readme_quote,
            )
        )
        predicted = case.expected_label if not case.mapping_is_coarse else Label.supported
        verdicts.append(
            Verdict(
                claim_id=claim_id, label=predicted, rationale="Synthetic report for the scorer."
            )
        )
    report = Report(
        tool_version="0.2.0",
        mode="test",
        project="synthetic",
        readme_path="README.md",
        generated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        claims=claims,
        verdicts=verdicts,
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "eval" / "score_verdicts.py"),
            str(ROOT / "eval" / "ground_truth" / "mempalace_issue_27.json"),
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Strict rows: 3/3" in completed.stdout
    assert "Coarse-mapping rows: 0/4" in completed.stdout
    assert "issue_severity=Misleading attribution" in completed.stdout
    assert "expected_label=contradicted" in completed.stdout
    assert "predicted_label=supported" in completed.stdout
