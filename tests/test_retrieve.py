"""Symbol index, text search, and deterministic numeric comparison."""

from pathlib import Path

from claimcheck.retrieve import (
    claim_numbers,
    compare_numbers,
    content_tokens,
    judge_numbers,
    parse_benchmarks,
    symbol_hits,
)

FIXTURE = Path("fixtures/tiny_repo")
README = FIXTURE / "README.md"


def test_python_symbol_index_finds_index_notes() -> None:
    hits = symbol_hits(
        FIXTURE, "The index_notes function writes a database.", skip=README.resolve()
    )
    assert (6, "tinylib/index.py", "index_notes") in hits


def test_parsers_read_json_csv_and_log() -> None:
    rows = parse_benchmarks(FIXTURE, skip=README.resolve())
    found = {(row.path, row.metric, row.raw) for row in rows}
    assert ("benchmarks/sample_results.json", "recall_at_5", "0.90") in found
    assert ("benchmarks/sample_results.csv", "accuracy", "0.70") in found
    assert ("benchmarks/run.log", "accuracy", "70%") in found


def test_percent_matches_a_fraction_and_conflicts_with_a_different_value() -> None:
    recall = judge_numbers("Recall at 5 on the bundled sample is 90%.", FIXTURE, readme=README)
    accuracy = judge_numbers("Sample accuracy is 99%.", FIXTURE, readme=README)
    haiku = judge_numbers(
        "A Haiku rerank reaches 100% on the bundled sample.", FIXTURE, readme=README
    )
    assert recall.relation == "match"
    assert accuracy.relation == "conflict"
    assert haiku.relation == "absent"


def test_bare_integers_are_not_treated_as_scores() -> None:
    assert claim_numbers("Recall at 5 on the bundled sample is 90%.")[0].raw == "90%"
    assert claim_numbers("There are 5 modules.") == []


def test_ratio_conflict_uses_the_raw_number() -> None:
    numbers = claim_numbers("Compression ratio is 30x.")
    from claimcheck.retrieve import Measurement

    judgment = compare_numbers(
        "Compression ratio is 30x.",
        numbers,
        [Measurement("results.json", 1, "compression_ratio", 8.0, "8")],
    )
    assert judgment.relation == "conflict"
    assert "ratio" in content_tokens("compression_ratio")
