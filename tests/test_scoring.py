"""Extraction recall against the MemPalace issue #27 rows, and the scorer script."""

import json
import subprocess
import sys
from pathlib import Path

from claimcheck.ground_truth import load_ground_truth
from claimcheck.scoring import score_extraction

ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "eval" / "ground_truth" / "mempalace_issue_27.json"

# One extracted string per gold row. Each should hit that row and no other row.
PROBES = {
    "mempalace-27-contradiction-detection": (
        "MemPalace catches mistakes before they reach you "
        "and checks facts against the knowledge graph."
    ),
    "mempalace-27-aaak-lossless-30x": (
        "AAAK claims 30x compression, zero information loss "
        "and describes itself as a lossless shorthand."
    ),
    "mempalace-27-longmemeval-96-6": (
        "The headline number is 96.6% LongMemEval R@5, positioned as MemPalace's score."
    ),
    "mempalace-27-palace-boost-34": "That structure alone improves retrieval by 34%.",
    "mempalace-27-haiku-rerank-100": "The table lists 100% with Haiku rerank.",
    "mempalace-27-closets-summaries": (
        "Closets are compressed summaries that point to the original content."
    ),
    "mempalace-27-hall-types": (
        "Halls are memory types — the same in every wing, acting as corridors."
    ),
}


def test_each_probe_matches_only_its_row() -> None:
    gold = load_ground_truth(GOLD_PATH)
    assert len(PROBES) == len(gold.cases)
    for case in gold.cases:
        result = score_extraction(gold.cases, [PROBES[case.id]])
        hit_ids = {item.id for item in gold.cases} - {miss.id for miss in result.misses}
        assert hit_ids == {case.id}


def test_numberless_paraphrase_does_not_recall_the_percentage_claim() -> None:
    gold = load_ground_truth(GOLD_PATH)
    result = score_extraction(gold.cases, ["retrieval boost from palace structure"])
    assert "mempalace-27-palace-boost-34" in {miss.id for miss in result.misses}
    bare = score_extraction(gold.cases, ["LongMemEval R@5"])
    assert "mempalace-27-longmemeval-96-6" in {miss.id for miss in bare.misses}


def test_empty_extraction_has_zero_recall_and_no_precision() -> None:
    gold = load_ground_truth(GOLD_PATH)
    result = score_extraction(gold.cases, [])
    assert result.recall == 0
    assert result.precision is None
    assert result.hits == 0


def test_score_script_reports_full_recall_for_the_probes(tmp_path: Path) -> None:
    extraction = tmp_path / "extracted.json"
    extraction.write_text(
        json.dumps({"claims": [{"text": text} for text in PROBES.values()]}),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "eval" / "score_extraction.py"),
            str(GOLD_PATH),
            str(extraction),
            "--min-recall",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "7/7" in completed.stdout
    assert "not verdict accuracy" in completed.stdout


def test_score_script_min_recall_fails_on_an_empty_extraction(tmp_path: Path) -> None:
    extraction = tmp_path / "extracted.json"
    extraction.write_text('{"claims": []}', encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "eval" / "score_extraction.py"),
            str(GOLD_PATH),
            str(extraction),
            "--min-recall",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
