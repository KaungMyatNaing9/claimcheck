"""The seeded eval file matches the issue it cites, and the package version matches."""

import re
from pathlib import Path

from claimcheck.constants import __version__
from claimcheck.ground_truth import load_ground_truth
from claimcheck.models import Label

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "ground_truth" / "mempalace_issue_27.json"
ISSUE = "https://github.com/MemPalace/mempalace/issues/27"
ACK = "https://github.com/MemPalace/mempalace/issues/27#issuecomment-4201242972"

EXPECTED = {
    "mempalace-27-contradiction-detection": "Feature does not exist",
    "mempalace-27-aaak-lossless-30x": "Claim is false",
    "mempalace-27-longmemeval-96-6": "Misleading attribution",
    "mempalace-27-palace-boost-34": "Misleading framing",
    "mempalace-27-haiku-rerank-100": "Unverifiable",
    "mempalace-27-closets-summaries": "Nomenclature mismatch",
    "mempalace-27-hall-types": "Conceptual, not functional",
}


def test_issue_27_file_has_the_seven_table_rows() -> None:
    gold = load_ground_truth(GOLD)
    assert gold.dataset == "mempalace-issue-27"
    assert gold.repo == "https://github.com/MemPalace/mempalace"
    assert gold.branch == "develop"
    assert gold.commit == "0808ad96c29d5acb9fd3b465025ea201711bd28d"
    assert gold.issue_url == ISSUE
    assert gold.issue_created_at == "2026-04-07T08:47:47Z"
    assert {case.id: case.issue_severity for case in gold.cases} == EXPECTED
    labels = {case.id: case.expected_label for case in gold.cases}
    assert labels["mempalace-27-haiku-rerank-100"] is Label.unverifiable
    assert all(
        label is Label.contradicted
        for case_id, label in labels.items()
        if case_id != "mempalace-27-haiku-rerank-100"
    )
    coarse = {case.id for case in gold.cases if case.mapping_is_coarse}
    assert coarse == {
        "mempalace-27-longmemeval-96-6",
        "mempalace-27-palace-boost-34",
        "mempalace-27-closets-summaries",
        "mempalace-27-hall-types",
    }


def test_every_row_cites_the_issue_body_and_the_acknowledgment_comment() -> None:
    gold = load_ground_truth(GOLD)
    for case in gold.cases:
        kinds = {source.kind for source in case.sources}
        urls = {source.url for source in case.sources}
        assert "issue_body" in kinds
        assert "issue_comment" in kinds
        assert ISSUE in urls
        assert ACK in urls
        assert case.evidence_notes.startswith("As written in the issue")
        assert case.readme_quote
        assert "ClaimCheck did not" in case.label_mapping_note or "not re-verified" in (
            case.label_mapping_note + case.evidence_notes
        )


def test_package_version_matches_pyproject() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == __version__
