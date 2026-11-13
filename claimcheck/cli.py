"""Command line: `extract` prints claims, `scan` writes a placeholder report."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from claimcheck.constants import __version__
from claimcheck.errors import ClaimCheckError, ConfigError, ReadmeError
from claimcheck.extract import extract_claims
from claimcheck.format import format_extraction, render_json, render_markdown
from claimcheck.llm import OpenAICompatibleClient, load_config_from_env, load_replay
from claimcheck.readme import is_git_url, load_readme
from claimcheck.scan import build_stub_report, project_name


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process status code and does not call sys.exit."""
    try:
        return _main(argv)
    except (ConfigError, ReadmeError) as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        return 2
    except ClaimCheckError as exc:
        print(f"claimcheck: {exc}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimcheck",
        description=(
            "Extract checkable claims from a README. "
            "Milestone 1 does not compare those claims to code or benchmark results."
        ),
    )
    parser.add_argument("--version", action="version", version=f"claimcheck {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser(
        "extract",
        help="Print claims found in a local README",
    )
    _add_common(extract)
    extract.add_argument(
        "--json",
        action="store_true",
        help="Print the extraction as JSON instead of text",
    )
    extract.add_argument(
        "--output",
        type=Path,
        help="Also write the extraction JSON to this file",
    )

    scan = subparsers.add_parser(
        "scan",
        help="Write report.md and report.json. Verdicts are unverifiable placeholders.",
    )
    _add_common(scan)
    scan.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for report.md and report.json (default: the working directory)",
    )

    args = parser.parse_args(argv)
    if args.max_attempts < 1:
        print("claimcheck: --max-attempts must be at least 1", file=sys.stderr)
        return 2
    if is_git_url(args.path):
        print(
            "claimcheck: cloning a git URL is not implemented in milestone 1. "
            "Pass a local directory or a README file. Remote scan is planned.",
            file=sys.stderr,
        )
        return 2
    document = load_readme(Path(args.path))
    client = _client(args.replay)
    if args.command == "extract":
        result = extract_claims(document, client, max_attempts=args.max_attempts)
        payload = result.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        sys.stdout.write(payload if args.json else format_extraction(result))
        return 0

    report = build_stub_report(
        document,
        client,
        project=project_name(document),
        generated_at=datetime.now(timezone.utc),
        max_attempts=args.max_attempts,
    )
    output_dir = args.output_dir if args.output_dir is not None else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(render_json(report), encoding="utf-8")
    checkable = sum(1 for claim in report.claims if claim.checkable)
    print(
        f"Wrote {markdown_path} and {json_path}. "
        f"{checkable} verdict(s), all unverifiable placeholders (milestone 1)."
    )
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="Local README file or a directory that contains one")
    parser.add_argument(
        "--replay",
        type=Path,
        help=(
            "Use a recorded model response instead of calling an API. "
            "A JSON list of strings is one response per attempt. "
            "Any other file is a single response, including a JSON object of claims."
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="How many model responses to accept before failing (default: 3)",
    )


def _client(replay: Path | None):
    if replay is not None:
        return load_replay(replay)
    config = load_config_from_env()
    return OpenAICompatibleClient(config)
