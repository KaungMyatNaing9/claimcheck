"""CLI extract and scan, using the recorded sample response. No network."""

from pathlib import Path

import pytest
from claimcheck.cli import main
from claimcheck.models import ExtractionResult, Label, Report

SAMPLE = Path("examples/northwind/README.md")
REPLAY = Path("examples/sample_extract_response.json")


def test_extract_replay_corrects_the_line_and_skips_fluff(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["extract", str(SAMPLE), "--replay", str(REPLAY)])
    assert code == 0
    output = capsys.readouterr().out
    assert "northwind/README.md:7" in output
    assert "northwind/README.md:9" in output
    assert "Skipped 1 not-checkable" in output
    assert "reported line 1" in output
    assert "best note tool" in output


def test_extract_json_is_the_extraction_schema(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output_path = tmp_path / "claims.json"
    code = main(
        [
            "extract",
            str(SAMPLE),
            "--replay",
            str(REPLAY),
            "--json",
            "--output",
            str(output_path),
        ]
    )
    assert code == 0
    payload = capsys.readouterr().out
    result = ExtractionResult.model_validate_json(payload)
    assert output_path.read_text(encoding="utf-8") == payload
    assert result.attempts == 1
    assert [claim.checkable for claim in result.claims].count(True) == 3
    assert result.claims[0].readme_line == 7


def test_scan_writes_a_placeholder_report(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        [
            "scan",
            str(SAMPLE),
            "--replay",
            str(REPLAY),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    summary = capsys.readouterr().out
    assert "not_found 2" in summary
    assert "unverifiable 1" in summary
    report = Report.model_validate_json((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert [verdict.label for verdict in report.verdicts] == [
        Label.not_found,
        Label.unverifiable,
        Label.not_found,
    ]
    assert report.mode == "milestone-2"
    assert all(verdict.evidence == [] for verdict in report.verdicts)
    assert len(report.verdicts) == 3


def test_missing_model_without_replay_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("CLAIMCHECK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    readme = tmp_path / "README.md"
    readme.write_text("# Local\n\nNothing numeric here.\n", encoding="utf-8")
    code = main(["extract", str(readme)])
    assert code == 2
    assert "CLAIMCHECK_MODEL" in capsys.readouterr().err


def test_max_attempts_must_be_positive(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["extract", str(SAMPLE), "--replay", str(REPLAY), "--max-attempts", "0"])
    assert code == 2
    assert "max-attempts" in capsys.readouterr().err


def test_missing_path_fails(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = main(["extract", str(tmp_path / "no-such-readme.md"), "--replay", str(REPLAY)])
    assert code == 2
    assert "does not exist" in capsys.readouterr().err
    assert capsys.readouterr().out == ""
