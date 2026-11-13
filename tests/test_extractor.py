"""Extractor validation, retries, and line correction. The model is a replay client."""

import json
from pathlib import Path

import pytest
from claimcheck.errors import ExtractionError
from claimcheck.extract import extract_claims
from claimcheck.llm import ReplayClient
from claimcheck.prompts import SYSTEM_PROMPT
from claimcheck.readme import ReadmeDocument


def _doc() -> ReadmeDocument:
    lines = (
        "# Demo",
        "",
        "The indexer writes a SQLite file.",
        "",
        "It is the best indexer ever.",
    )
    return ReadmeDocument(path=Path("README.md"), display_path="README.md", lines=lines)


def _payload(claims: list[dict]) -> str:
    return json.dumps({"claims": claims})


def _feature(line: int = 3) -> dict:
    return {
        "text": "The indexer writes a SQLite file.",
        "kind": "feature",
        "quote": "The indexer writes a SQLite file.",
        "line": line,
        "checkable": True,
        "skip_reason": None,
    }


def test_prompt_asks_for_kinds_and_forbids_a_truth_judgment() -> None:
    assert "benchmark_number" in SYSTEM_PROMPT
    assert "feature" in SYSTEM_PROMPT
    assert "property" in SYSTEM_PROMPT
    assert "compatibility" in SYSTEM_PROMPT
    assert "Do not say whether a claim is true" in SYSTEM_PROMPT
    assert "verbatim" in SYSTEM_PROMPT


def test_valid_response_maps_the_quote_and_keeps_fluff_marked() -> None:
    fluff = {
        "text": "It is the best indexer ever.",
        "kind": "other",
        "quote": "It is the best indexer ever.",
        "line": 5,
        "checkable": False,
        "skip_reason": "marketing superlative",
    }
    client = ReplayClient([_payload([_feature(), fluff])])
    result = extract_claims(_doc(), client)
    assert result.attempts == 1
    assert [(claim.id, claim.readme_line, claim.checkable) for claim in result.claims] == [
        ("c001", 3, True),
        ("c002", 5, False),
    ]
    assert result.claims[1].skip_reason == "marketing superlative"


def test_wrong_line_number_is_replaced_with_the_quotes_line() -> None:
    client = ReplayClient([_payload([_feature(line=1)])])
    result = extract_claims(_doc(), client)
    assert result.claims[0].readme_line == 3
    assert result.warnings
    assert "reported line 1" in result.warnings[0]


def test_malformed_output_is_retried_and_then_accepted() -> None:
    client = ReplayClient(["this is not json", _payload([_feature()])])
    result = extract_claims(_doc(), client)
    assert result.attempts == 2
    assert len(client.calls) == 2
    assert "rejected" in client.calls[1]["user"]
    assert result.claims[0].text.startswith("The indexer")


def test_quote_missing_from_the_readme_is_retried() -> None:
    bad = _feature()
    bad["quote"] = "a sentence that was never written"
    client = ReplayClient([_payload([bad]), _payload([_feature()])])
    result = extract_claims(_doc(), client, max_attempts=2)
    assert result.attempts == 2
    assert "was not found" in client.calls[1]["user"]


def test_exhausted_retries_raise() -> None:
    client = ReplayClient(["nope", "still nope", "{}"])
    with pytest.raises(ExtractionError) as caught:
        extract_claims(_doc(), client, max_attempts=3)
    assert caught.value.attempts == 3
    assert caught.value.errors


def test_unknown_kind_is_rejected() -> None:
    bad = _feature()
    bad["kind"] = "speed"
    client = ReplayClient([_payload([bad])])
    with pytest.raises(ExtractionError, match="invalid"):
        extract_claims(_doc(), client, max_attempts=1)


def test_empty_claim_list_is_valid() -> None:
    result = extract_claims(_doc(), ReplayClient(['{"claims": []}']))
    assert result.claims == []
