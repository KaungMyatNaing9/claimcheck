#!/usr/bin/env python3
"""Score a report's labels against hand-labeled claims.

Strict rows and coarse-mapping rows are printed separately. Each row shows
the issue severity beside the expected label and the predicted label.
"""

import argparse
import json
import sys
from pathlib import Path

from claimcheck.errors import GroundTruthError
from claimcheck.ground_truth import load_ground_truth
from claimcheck.models import Report
from claimcheck.scoring import DEFAULT_RECALL_THRESHOLD
from claimcheck.verdict_score import score_verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("report", type=Path, help="report.json from claimcheck scan")
    parser.add_argument("--threshold", type=float, default=DEFAULT_RECALL_THRESHOLD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        gold = load_ground_truth(args.ground_truth)
        report = Report.model_validate_json(args.report.read_text(encoding="utf-8"))
        result = score_verdicts(gold.cases, report, threshold=args.threshold)
    except (GroundTruthError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"score_verdicts: {exc}", file=sys.stderr)
        return 2
    if args.json:
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
        return 0
    print(
        f"Strict rows: {result.strict_correct}/{result.strict_total} agreed with the mapped label."
    )
    print(
        f"Coarse-mapping rows: {result.coarse_correct}/{result.coarse_total} "
        "agreed with the mapped label."
    )
    print(f"Gold claims matched to a report claim: {result.matched}/{result.gold}.")
    print(result.note)
    print()
    _print_group("Strict", [row for row in result.rows if not row.mapping_is_coarse])
    _print_group("Coarse mapping", [row for row in result.rows if row.mapping_is_coarse])
    return 0


def _print_group(title: str, rows: list) -> None:
    print(f"## {title}")
    if not rows:
        print("(none)")
        print()
        return
    for row in rows:
        predicted = "unmatched" if row.predicted_label is None else row.predicted_label.value
        print(
            f"- {row.id}: issue_severity={row.issue_severity}; "
            f"expected_label={row.expected_label.value}; predicted_label={predicted}"
        )
    print()


if __name__ == "__main__":
    raise SystemExit(main())
