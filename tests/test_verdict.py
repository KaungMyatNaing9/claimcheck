"""Verdict policy: citations must be retrieved, and contradicted needs a second pass."""

import json
from pathlib import Path

from claimcheck.llm import ReplayClient
from claimcheck.models import Label
from claimcheck.readme import load_readme
from claimcheck.scan import build_report

FIXTURE = Path("fixtures/tiny_repo")


def _extract() -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "text": "TinyLib detects contradictions in stored facts before saving them.",
                    "kind": "feature",
                    "quote": "TinyLib detects contradictions in stored facts before saving them.",
                    "line": 7,
                    "checkable": True,
                    "skip_reason": None,
                }
            ]
        }
    )


def test_unconfirmed_contradiction_is_downgraded() -> None:
    client = ReplayClient(
        [
            _extract(),
            json.dumps(
                {
                    "label": "contradicted",
                    "citations": ["tinylib/facts.py:5"],
                    "rationale": "The docstring says it does not check.",
                }
            ),
            json.dumps({"confirm": False, "rationale": "Not sure this line is enough."}),
        ]
    )
    report = build_report(load_readme(FIXTURE), client, repo_root=FIXTURE)
    verdict = report.verdicts[0]
    assert verdict.label is Label.unverifiable
    assert verdict.provisional is True
    assert verdict.downgraded_from is Label.contradicted


def test_citation_outside_the_retrieved_lines_is_dropped() -> None:
    sentence = "The index_notes function writes a SQLite database at notes.db."
    client = ReplayClient(
        [
            json.dumps(
                {
                    "claims": [
                        {
                            "text": sentence,
                            "kind": "feature",
                            "quote": sentence,
                            "line": 5,
                            "checkable": True,
                            "skip_reason": None,
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "label": "supported",
                    "citations": ["missing.py:1"],
                    "rationale": "A file that was not retrieved.",
                }
            ),
        ]
    )
    report = build_report(load_readme(FIXTURE), client, repo_root=FIXTURE)
    verdict = report.verdicts[0]
    assert verdict.label is Label.unverifiable
    assert verdict.evidence == []
    assert verdict.downgraded_from is Label.supported
