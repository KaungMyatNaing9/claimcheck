#!/usr/bin/env python3
"""Score extraction recall against a hand-labeled ground-truth file.

This does not score verdicts. It does not call a model. Pass JSON from
`claimcheck extract --json` or `--output`.
"""

import argparse
import sys
from pathlib import Path

from claimcheck.errors import GroundTruthError
from claimcheck.ground_truth import load_ground_truth
from claimcheck.scoring import DEFAULT_RECALL_THRESHOLD, load_extracted_texts, score_extraction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ground_truth", type=Path, help="Hand-labeled JSON file")
    parser.add_argument("extraction", type=Path, help="Extraction or report JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_RECALL_THRESHOLD,
        help=f"Token-overlap threshold (default: {DEFAULT_RECALL_THRESHOLD})",
    )
    parser.add_argument("--json", action="store_true", help="Print the score as JSON")
    parser.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="Exit 1 when recall is below this value",
    )
    args = parser.parse_args(argv)
    if args.min_recall is not None and not 0.0 <= args.min_recall <= 1.0:
        print("score_extraction: --min-recall must be between 0 and 1", file=sys.stderr)
        return 2
    try:
        gold = load_ground_truth(args.ground_truth)
        texts = load_extracted_texts(args.extraction)
        result = score_extraction(gold.cases, texts, threshold=args.threshold)
    except (GroundTruthError, ValueError) as exc:
        print(f"score_extraction: {exc}", file=sys.stderr)
        return 2
    if args.json:
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    else:
        precision = "n/a" if result.precision is None else f"{result.precision:.3f}"
        print(f"Extraction recall: {result.recall:.3f} ({result.hits}/{result.gold})")
        print(
            f"Extraction precision: {precision} "
            f"({result.extracted_matched}/{result.extracted} extracted texts matched a gold claim)"
        )
        print(f"Token-overlap threshold: {result.threshold}")
        print(result.note)
        if result.misses:
            print("Missed:")
            for miss in result.misses:
                print(f"- {miss.id}: {miss.claim_text}")
    if args.min_recall is not None and result.recall < args.min_recall:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
